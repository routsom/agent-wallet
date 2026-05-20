"""CLI command: agent-wallet status"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy

console = Console()


def status(
    wallet: str | None = typer.Option(None, "--wallet", "-w", help="Wallet name"),
    db: str | None = typer.Option(None, "--db", help="Database path"),
) -> None:
    """Show today's spend, budget remaining, and paused status."""
    ledger = Ledger(db_path=db)

    try:
        wallets = ledger.list_wallets()

        if wallet:
            wallets = [w for w in wallets if w["name"] == wallet]
            if not wallets:
                console.print(f"[red]Wallet '{wallet}' not found.[/red]")
                raise typer.Exit(1)

        if not wallets:
            console.print("[yellow]No wallets found.[/yellow]")
            return

        table = Table(title="💰 Agent Wallet Status", show_lines=True)
        table.add_column("Wallet", style="cyan bold")
        table.add_column("Status", justify="center")
        table.add_column("Today Spend", justify="right", style="green")
        table.add_column("Daily Limit", justify="right")
        table.add_column("Weekly Spend", justify="right", style="green")
        table.add_column("Weekly Limit", justify="right")
        table.add_column("Lifetime", justify="right", style="dim")

        for w in wallets:
            policy = BudgetPolicy.from_json(w["policy"])

            # Daily
            daily_period = BudgetPeriod(type="daily", limit_usd=0, reset_hour=0)
            daily_since = policy.get_period_start(daily_period)
            daily_spend = ledger.get_spend_since(w["id"], daily_since)
            daily_limit = next(
                (p.limit_usd for p in policy.periods if p.type == "daily"),
                None,
            )

            # Weekly
            weekly_period = BudgetPeriod(type="weekly", limit_usd=0, reset_hour=0)
            weekly_since = policy.get_period_start(weekly_period)
            weekly_spend = ledger.get_spend_since(w["id"], weekly_since)
            weekly_limit = next(
                (p.limit_usd for p in policy.periods if p.type == "weekly"),
                None,
            )

            # Lifetime
            lifetime_spend = ledger.get_total_spend(w["id"])

            # Status
            status_text = "[red]⏸ PAUSED[/red]" if w["paused"] else "[green]▶ active[/green]"

            # Budget bar for daily
            daily_str = f"${daily_spend:.4f}"
            daily_limit_str = f"${daily_limit:.2f}" if daily_limit else "—"
            weekly_str = f"${weekly_spend:.4f}"
            weekly_limit_str = f"${weekly_limit:.2f}" if weekly_limit else "—"

            table.add_row(
                w["name"],
                status_text,
                daily_str,
                daily_limit_str,
                weekly_str,
                weekly_limit_str,
                f"${lifetime_spend:.4f}",
            )

        console.print(table)
    finally:
        ledger.close()
