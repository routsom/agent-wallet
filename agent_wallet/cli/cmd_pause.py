"""CLI command: agent-wallet pause"""

from __future__ import annotations

import typer
from rich.console import Console

from agent_wallet.ledger import Ledger

console = Console()


def pause(
    wallet: str = typer.Argument(..., help="Wallet name to pause"),
    db: str | None = typer.Option(None, "--db", help="Database path"),
) -> None:
    """Manually pause a wallet. Same effect as kill switch STOP command."""
    ledger = Ledger(db_path=db)

    try:
        w = ledger.get_wallet_by_name(wallet)
        if not w:
            console.print(f"[red]Wallet '{wallet}' not found.[/red]")
            raise typer.Exit(1)

        if w["paused"]:
            console.print(f"[yellow]Wallet '{wallet}' is already paused.[/yellow]")
            return

        ledger.pause_wallet(w["id"])
        ledger.log_kill_switch_event(
            wallet_id=w["id"],
            platform="cli",
            command=f"pause {wallet}",
            action="pause",
        )
        console.print(f"[green]✓ Wallet '{wallet}' paused.[/green]")
    finally:
        ledger.close()
