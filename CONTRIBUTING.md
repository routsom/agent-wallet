# Contributing to agent-wallet

Thank you for your interest in contributing! This document explains the process.

## Getting Started

```bash
git clone https://github.com/your-org/agent-wallet.git
cd agent-wallet
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
mypy agent_wallet/ --strict
ruff check agent_wallet/
```

All three must pass before submitting a PR.

## Adding a New Provider

1. Create `agent_wallet/interceptors/<provider>.py`
2. Implement token counting for that provider's response format
3. Add pricing entries to `agent_wallet/pricing.yaml`
4. Add tests in `tests/unit/test_interceptors.py`
5. Add an example in `examples/`

See `agent_wallet/interceptors/anthropic.py` as a reference implementation.

## Adding a New Kill Switch Platform

1. Create `agent_wallet/killswitch/<platform>.py` subclassing `KillSwitchBase`
2. Implement `platform_name`, `poll()`, and `reply()` methods
3. Register in `agent_wallet/killswitch/__init__.py`
4. Add the platform name to `KillSwitchConfig.platform` literals in `policy.py`

## Testing Rules

- Use `:memory:` SQLite for all unit tests — no temp files
- Mock provider API calls with `unittest.mock.patch` — no live API calls
- Use `freezegun` for any test involving time or daily reset logic
- Integration tests use a temp file deleted after each test

## Pull Request Guidelines

- One logical change per PR
- Include tests for any new behaviour
- Update `pricing.yaml` if adding model support
- Do not add async to `wallet.py` or `ledger.py` — see CLAUDE.md §6

## Code Style

- Formatted and linted with `ruff`
- Type-checked with `mypy --strict`
- Line length: 100 characters

## Engineering Principles

See `CLAUDE.md` for the full list. Key ones:

- **Never silently pass a budget-exceeded call** — that defeats the purpose
- **Never block on ledger write** — ledger errors are non-fatal warnings only
- **Never store provider API keys** — the wallet wraps the client, never reads creds
