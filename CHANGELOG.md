# Changelog

All notable changes to agent-wallet will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release: `AgentWallet`, `Wallet`, `Ledger`, `BudgetPolicy`
- Anthropic SDK interceptor (`WrappedAnthropic`)
- OpenAI SDK interceptor (`WrappedOpenAI`)
- Google Gemini interceptor (`WrappedGoogle`)
- Ollama interceptor (`WrappedOllama`)
- Telegram kill switch and alerts
- Discord kill switch and alerts
- Generic webhook kill switch and alerts
- Auto-downgrade: switch to cheaper model as budget tightens
- CLI: `agent-wallet status/pause/resume/history/wallets`
- Local SQLite spend ledger with WAL mode and atomic writes
- Bundled pricing manifest for Anthropic, OpenAI, Google, Ollama
- `AGENT_WALLET_DISABLED=1` escape hatch for testing
