# 💰 agent-wallet

> Add two lines of code and your agent can never spend more than you allow. Ever. Even while you sleep.

**agent-wallet** is a drop-in middleware library that gives AI agents hard spending limits, token budgets, circuit breakers, and real-time kill switches via messaging apps (Telegram, WhatsApp, Discord).

## The Problem

Agents running overnight can spend hundreds of dollars before anyone notices. Cost surprises are the #1 complaint from OpenClaw users — one documented case shows a single "hi" message costing $11 with a premium model. No existing OSS library enforces budget constraints at the provider call level.

## Quick Start

```bash
pip install sr-agent-wallet
```

```python
from agent_wallet import AgentWallet
from anthropic import Anthropic

wallet = AgentWallet(daily_limit_usd=5.00, kill_switch='telegram')
client = wallet.wrap(Anthropic())  # drop-in replacement

# Use exactly like the original client — but with budget enforcement
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## Features

- 🔒 **Hard spend caps** per day / week / session in USD
- 👛 **Per-agent wallets** with isolated budgets
- 📉 **Auto-downgrade** — switches to a cheaper model as budget tightens
- 🛑 **Kill switch** — text "STOP" to Telegram/Discord → agent pauses instantly
- 🔔 **Alerts** at configurable thresholds (default: 80%)
- 📊 **Local SQLite ledger** — no cloud, no dashboard required
- 🔌 **Multi-provider** — Anthropic, OpenAI, Google Gemini, Ollama

## Auto-Downgrade

Automatically switch to cheaper models as your budget tightens:

```python
from agent_wallet import AgentWallet, AutoDowngradeStep

wallet = AgentWallet(
    name="research-bot",
    daily_limit_usd=10.00,
    auto_downgrade=[
        AutoDowngradeStep(
            at_budget_pct=0.6,
            from_model="claude-opus-4-6",
            to_model="claude-sonnet-4-6",
            provider="anthropic",
        ),
        AutoDowngradeStep(
            at_budget_pct=0.85,
            from_model="claude-sonnet-4-6",
            to_model="claude-haiku-4-5-20251001",
            provider="anthropic",
        ),
    ],
)
```

## Kill Switch

Send a message from your phone to pause any agent instantly:

```
STOP research-bot     → pauses the wallet
RESUME research-bot   → resumes it
STATUS                → shows all wallet statuses
```

### Supported platforms
- **Telegram** — set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- **Discord** — set `DISCORD_WEBHOOK_URL`
- **Generic webhook** — any HTTP endpoint

## CLI

```bash
agent-wallet status                    # show all wallets
agent-wallet status --wallet my-agent  # show specific wallet
agent-wallet pause my-agent            # pause a wallet
agent-wallet resume my-agent           # resume a wallet
agent-wallet history --days 7          # show spend history
agent-wallet wallets list              # list all wallets
agent-wallet wallets create bot --daily 10.00
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_WALLET_DB` | `~/.agent-wallet/ledger.db` | SQLite database path |
| `AGENT_WALLET_PRICING` | `(bundled)` | Custom pricing manifest |
| `AGENT_WALLET_DISABLED` | unset | Set to `1` to disable all interception |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID |
| `DISCORD_WEBHOOK_URL` | — | Discord webhook URL |

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
mypy agent_wallet/ --strict
ruff check agent_wallet/
```

## License

MIT
