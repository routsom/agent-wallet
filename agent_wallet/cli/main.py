"""Typer CLI entry point for agent-wallet.

Usage:
    agent-wallet status [--wallet <name>]
    agent-wallet pause <wallet>
    agent-wallet resume <wallet>
    agent-wallet history [--wallet <name>] [--days 7] [--format table|json|csv]
    agent-wallet wallets list
    agent-wallet wallets create <name> --daily <usd> [--weekly <usd>]
"""

from __future__ import annotations

import typer

from agent_wallet.cli.cmd_history import history
from agent_wallet.cli.cmd_pause import pause
from agent_wallet.cli.cmd_resume import resume
from agent_wallet.cli.cmd_status import status
from agent_wallet.cli.cmd_wallets import wallets_app

app = typer.Typer(
    name="agent-wallet",
    help="💰 AI agent spending limits, budgets, and kill switches.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register commands
app.command("status")(status)
app.command("pause")(pause)
app.command("resume")(resume)
app.command("history")(history)

# Register sub-app
app.add_typer(wallets_app, name="wallets", help="Manage wallets.")


if __name__ == "__main__":
    app()
