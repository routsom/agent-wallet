# CLAUDE.md — agent-wallet

> Instructions for Claude Code working on this repository.
> Read this entire file before touching any code.

---

## Project Overview

**agent-wallet** is a drop-in middleware library that gives AI agents hard
spending limits, token budgets, circuit breakers, and real-time kill switches
via messaging apps (Telegram, WhatsApp, Discord).

The problem it solves: agents running overnight can spend hundreds of dollars
before anyone notices. Cost surprises are the #1 complaint from OpenClaw users —
one documented case shows a single "hi" message costing $11 with a premium
model. No existing OSS library enforces budget constraints at the provider call
level.

**North star:** add two lines of code and your agent can never spend more than
you allow. Ever. Even while you sleep.

```typescript
const wallet = new AgentWallet({ dailyLimitUsd: 5.00, killSwitch: 'telegram' });
const client = wallet.wrap(new Anthropic()); // drop-in replacement
```

### Core capabilities
- Hard spend caps per day / week / session in USD
- Per-agent named wallets with isolated budgets
- Auto-downgrade: switches to a cheaper model as budget tightens
- Kill switch: text "STOP" to your Telegram/WhatsApp/Discord bot → agent pauses
- Alerts at configurable thresholds (default: 80%)
- Local SQLite spend ledger — no cloud, no dashboard required
- Works with Anthropic, OpenAI, Google Gemini, Ollama

---

## Repository Layout

```
agent-wallet/
├── CLAUDE.md
├── README.md
├── pyproject.toml            ← Python package (primary)
├── package.json              ← TypeScript package (secondary)
├── tsconfig.json
│
├── agent_wallet/             ← Python package root
│   ├── __init__.py           ← public API: AgentWallet, Wallet, BudgetPolicy
│   ├── wallet.py             ← core Wallet class
│   ├── ledger.py             ← SQLite spend ledger
│   ├── policy.py             ← BudgetPolicy + AutoDowngrade logic
│   ├── interceptors/
│   │   ├── __init__.py
│   │   ├── anthropic.py      ← Anthropic SDK interceptor
│   │   ├── openai.py         ← OpenAI SDK interceptor
│   │   ├── google.py         ← Google Gemini interceptor
│   │   └── ollama.py         ← Ollama interceptor (token count estimation)
│   ├── killswitch/
│   │   ├── __init__.py
│   │   ├── base.py           ← KillSwitch abstract base
│   │   ├── telegram.py       ← Telegram polling kill switch
│   │   ├── discord.py        ← Discord webhook kill switch
│   │   └── webhook.py        ← Generic HTTP webhook kill switch
│   ├── alerts/
│   │   ├── __init__.py
│   │   ├── base.py           ← Alert abstract base
│   │   ├── telegram.py
│   │   ├── discord.py
│   │   └── webhook.py
│   └── cli/
│       ├── __init__.py
│       ├── main.py           ← Typer CLI entry point
│       ├── cmd_status.py
│       ├── cmd_pause.py
│       ├── cmd_resume.py
│       ├── cmd_history.py
│       └── cmd_wallets.py
│
├── ts/                       ← TypeScript SDK
│   └── src/
│       ├── index.ts
│       ├── wallet.ts
│       ├── ledger.ts         ← better-sqlite3
│       ├── policy.ts
│       └── interceptors/
│           ├── anthropic.ts
│           └── openai.ts
│
├── tests/
│   ├── unit/
│   │   ├── test_wallet.py
│   │   ├── test_ledger.py
│   │   ├── test_policy.py
│   │   └── test_interceptors.py
│   └── integration/
│       └── test_budget_enforcement.py
│
└── examples/
    ├── basic_anthropic.py
    ├── multi_wallet.py
    ├── telegram_killswitch.py
    └── typescript_example.ts
```

---

## Core Data Models

```python
# agent_wallet/policy.py

@dataclass
class BudgetPeriod:
    type: str           # "daily" | "weekly" | "session" | "lifetime"
    limit_usd: float
    reset_hour: int = 0  # UTC hour for daily reset (default: midnight)

@dataclass
class AutoDowngradeStep:
    at_budget_pct: float   # trigger when this % of budget is spent
    from_model: str
    to_model: str
    provider: str

@dataclass
class BudgetPolicy:
    periods: list[BudgetPeriod]
    alert_thresholds: list[float]  # e.g. [0.8, 1.0] for 80% and 100%
    fail_mode: str                 # "pause" | "error" | "downgrade"
    auto_downgrade: list[AutoDowngradeStep] | None = None

@dataclass
class AlertConfig:
    channels: list[str]            # ["telegram", "discord", "webhook"]
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    webhook_url: str | None = None

@dataclass
class KillSwitchConfig:
    platform: str                  # "telegram" | "discord" | "webhook"
    command: str = "STOP"          # message that triggers pause
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    poll_interval_seconds: int = 5

# agent_wallet/ledger.py

@dataclass
class SpendRecord:
    id: str                  # UUID4
    wallet_id: str
    recorded_at: str         # ISO-8601
    provider: str            # "anthropic" | "openai" | "google" | "ollama"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    session_id: str | None
    metadata: dict           # arbitrary key-value from user
```

---

## SQLite Schema

Database at `~/.agent-wallet/ledger.db` (override with `AGENT_WALLET_DB`).

```sql
CREATE TABLE wallets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,  -- 1 = paused by kill switch
    policy TEXT NOT NULL                -- JSON-serialized BudgetPolicy
);

CREATE TABLE spend_records (
    id TEXT PRIMARY KEY,
    wallet_id TEXT NOT NULL REFERENCES wallets(id),
    recorded_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL,
    session_id TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE kill_switch_events (
    id TEXT PRIMARY KEY,
    wallet_id TEXT NOT NULL REFERENCES wallets(id),
    triggered_at TEXT NOT NULL,
    platform TEXT NOT NULL,
    command TEXT NOT NULL,
    action TEXT NOT NULL    -- "pause" | "resume"
);

CREATE INDEX idx_spend_wallet_time ON spend_records(wallet_id, recorded_at);
CREATE INDEX idx_spend_session ON spend_records(session_id);
```

---

## Interceptor Pattern

Each provider interceptor wraps the provider's client and intercepts every API
call. The interception order is:

```
user calls client.messages.create(...)
            │
            ▼
    ┌──────────────────┐
    │  PRE-FLIGHT CHECK │  → check budget, check paused, maybe downgrade model
    └────────┬─────────┘
             │ approved
             ▼
    ┌──────────────────┐
    │  ORIGINAL CALL    │  → call real provider API
    └────────┬─────────┘
             │ response
             ▼
    ┌──────────────────┐
    │  RECORD SPEND     │  → write SpendRecord to ledger (atomic)
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │  POST-FLIGHT CHECK│  → check if threshold crossed, trigger alert
    └────────┬─────────┘
             │
             ▼
    return response to user
```

```python
# agent_wallet/interceptors/anthropic.py (simplified)

class WrappedAnthropic:
    def __init__(self, client: Anthropic, wallet: Wallet):
        self._client = client
        self._wallet = wallet
        self.messages = WrappedMessages(client.messages, wallet)

class WrappedMessages:
    def create(self, **kwargs):
        # 1. Pre-flight
        model = self._wallet.policy.maybe_downgrade(kwargs["model"])
        kwargs["model"] = model
        self._wallet.check_budget_or_raise()  # raises BudgetExceededError

        # 2. Original call
        response = self._client.messages.create(**kwargs)

        # 3. Record
        self._wallet.ledger.record(
            provider="anthropic",
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=calculate_cost("anthropic", model, response.usage),
        )

        # 4. Post-flight alerts (non-blocking)
        self._wallet.maybe_alert_async()

        return response
```

---

## Auto-Downgrade Configuration

```python
wallet = AgentWallet(
    name="research-bot",
    daily_limit_usd=10.00,
    auto_downgrade=[
        AutoDowngradeStep(
            at_budget_pct=0.6,                    # at 60% spent...
            from_model="claude-opus-4-6",
            to_model="claude-sonnet-4-6",
            provider="anthropic",
        ),
        AutoDowngradeStep(
            at_budget_pct=0.85,                   # at 85% spent...
            from_model="claude-sonnet-4-6",
            to_model="claude-haiku-4-5-20251001",
            provider="anthropic",
        ),
    ]
)
```

The downgrade chain applies to the model name in the intercepted call.
If the requested model doesn't match any `from_model`, it passes through
unchanged — never error, never block.

---

## Kill Switch

The kill switch runs as a background thread/task polling the messaging platform.

```
Background thread polls Telegram every 5s
    │
    user sends: "STOP research-bot"
    │
    ▼
KillSwitch.on_message("STOP research-bot")
    │
    ├─ parse: command="STOP", wallet_name="research-bot"
    ├─ ledger.pause_wallet("research-bot")
    ├─ log KillSwitchEvent
    └─ reply: "✓ research-bot paused. Budget: $4.23 / $10.00 today."

Next call to client.messages.create(...)
    │
    ▼
check_budget_or_raise()
    └─ wallet.paused == True → raises WalletPausedError
```

Commands (configurable):
- `STOP <wallet>` — pause wallet
- `RESUME <wallet>` — resume wallet
- `STATUS` — reply with all wallet statuses and today's spend

---

## CLI Reference

```
agent-wallet status [--wallet <name>]
    Show today's spend, budget remaining, and paused status for all wallets
    (or a specific wallet). Outputs a table.

agent-wallet pause <wallet>
    Manually pause a wallet. Same effect as kill switch STOP command.

agent-wallet resume <wallet>
    Resume a paused wallet.

agent-wallet history [--wallet <name>] [--days 7] [--format table|json|csv]
    Show spend history. Groups by day and model.

agent-wallet wallets list
    List all registered wallets with their policies.

agent-wallet wallets create <name> --daily <usd> [--weekly <usd>]
    Create a new named wallet interactively.

All commands accept --db <path> to override database location.
```

---

## Engineering Principles

### 1. Never block user code on non-budget errors
If ledger write fails, alert fails, or kill switch polling errors — log a
warning and continue. The only thing that should block a call is an actual
budget violation. Instrumentation must never be load-bearing.

```python
# CORRECT
try:
    self.ledger.record(...)
except Exception as e:
    logger.warning(f"agent-wallet: ledger write failed: {e}")
    # call continues

# WRONG
self.ledger.record(...)  # raises, kills the agent call
```

### 2. Fail-closed on budget exceeded
When budget is exceeded, the default `fail_mode` is `"pause"` — raises
`BudgetExceededError`. User can configure `"error"` (same) or `"downgrade"`
(try cheaper model). There is no silent pass-through on budget exceeded.

### 3. Atomic ledger writes
Every `SpendRecord` is written in a single SQLite transaction. Partial writes
must never occur. Use `BEGIN IMMEDIATE` for write transactions.

### 4. Model names are stored as-is
Never normalise model names in the ledger. Store exactly what the provider
returns. Normalisation belongs in cost calculation with a fallback.

### 5. Kill switch is additive, not the only gate
The kill switch pauses the wallet in the ledger. The pre-flight check reads
`wallet.paused` from the ledger on every call. They are independent — pausing
via CLI and pausing via kill switch both set the same ledger flag.

### 6. No async in the Python core
`wallet.py`, `ledger.py`, `policy.py` are synchronous. Async wrappers for async
frameworks live in `interceptors/`. The kill switch background poller is a
`threading.Thread`, not an asyncio task.

---

## Testing Rules

- Budget enforcement: use `time_machine` or `freezegun` to test daily reset
  logic. Never rely on wall clock time in tests.
- Interceptors: mock provider API calls with `unittest.mock.patch`. Never hit
  a live API.
- Ledger: use an in-memory SQLite (`:memory:`) for all unit tests. Integration
  tests use a temp file that is deleted after each test.
- Kill switch: mock the messaging platform polling loop. Test that
  `ledger.pause_wallet()` is called on the right command.
- Auto-downgrade: assert the `model` argument passed to the provider call is
  the downgraded model, not the original.

```bash
pytest tests/ -v
mypy agent_wallet/ --strict
ruff check agent_wallet/
```

---

## Common Tasks

### Adding a new provider

1. Create `agent_wallet/interceptors/<provider>.py`
2. Implement token counting specific to that provider's response format
3. Add pricing entries to `agent_wallet/pricing.yaml`
4. Add tests in `tests/unit/test_interceptors.py`
5. Add an example in `examples/`

### Adding a new kill switch platform

1. Create `agent_wallet/killswitch/<platform>.py` subclassing `KillSwitchBase`
2. Implement `start_polling()` and `stop_polling()` methods
3. Register in `agent_wallet/killswitch/__init__.py`
4. Add the platform name to `KillSwitchConfig.platform` literals
5. Document in README

---

## What Not To Do

- **Never silently pass a budget-exceeded call** — that defeats the purpose.
- **Never block on ledger write** — ledger errors are non-fatal, warnings only.
- **Never store provider API keys** — the wallet wraps the client but never
  reads or stores its credentials.
- **Never add a web dashboard** — out of scope. CLI + messaging app is the UI.
- **Never auto-resume a paused wallet** — only explicit `RESUME` command or
  CLI `resume` should un-pause. Budget reset (midnight) does not auto-resume.
- **Don't add async to the core** — keep `wallet.py` and `ledger.py` sync.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_WALLET_DB` | `~/.agent-wallet/ledger.db` | SQLite database path |
| `AGENT_WALLET_PRICING` | `(bundled pricing.yaml)` | Custom pricing manifest |
| `AGENT_WALLET_DISABLED` | unset | Set to `1` to disable all interception |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for kill switch / alerts |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for kill switch / alerts |
| `DISCORD_WEBHOOK_URL` | — | Discord webhook for kill switch / alerts |

---

## Dependencies

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "rich>=13",
    "pyyaml>=6",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.30"]
openai    = ["openai>=1.30"]
google    = ["google-generativeai>=0.7"]
telegram  = ["python-telegram-bot>=21.0"]
discord   = ["discord.py>=2.3"]
dev       = ["pytest", "mypy", "ruff", "pytest-cov", "freezegun"]
```
