"""CLI command: agent-wallet resume"""

from __future__ import annotations

import typer
from rich.console import Console

from agent_wallet.ledger import Ledger

console = Console()


def resume(
    wallet: str = typer.Argument(..., help="Wallet name to resume"),
    db: str | None = typer.Option(None, "--db", help="Database path"),
) -> None:
    """Resume a paused wallet."""
    ledger = Ledger(db_path=db)

    try:
        w = ledger.get_wallet_by_name(wallet)
        if not w:
            console.print(f"[red]Wallet '{wallet}' not found.[/red]")
            raise typer.Exit(1)

        if not w["paused"]:
            console.print(f"[yellow]Wallet '{wallet}' is not paused.[/yellow]")
            return

        ledger.resume_wallet(w["id"])
        ledger.log_kill_switch_event(
            wallet_id=w["id"],
            platform="cli",
            command=f"resume {wallet}",
            action="resume",
        )
        console.print(f"[green]✓ Wallet '{wallet}' resumed.[/green]")
    finally:
        ledger.close()
