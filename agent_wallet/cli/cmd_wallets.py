"""CLI command: agent-wallet wallets list/create"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy

console = Console()

wallets_app = typer.Typer(
    name="wallets",
    help="Manage wallets.",
    no_args_is_help=True,
)


@wallets_app.command("list")
def list_wallets(
    db: str | None = typer.Option(None, "--db", help="Database path"),
) -> None:
    """List all registered wallets with their policies."""
    ledger = Ledger(db_path=db)

    try:
        wallets = ledger.list_wallets()

        if not wallets:
            console.print("[yellow]No wallets found.[/yellow]")
            return

        table = Table(title="💰 Registered Wallets", show_lines=True)
        table.add_column("Name", style="cyan bold")
        table.add_column("ID", style="dim")
        table.add_column("Created", style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Daily Limit", justify="right")
        table.add_column("Weekly Limit", justify="right")
        table.add_column("Fail Mode", justify="center")

        for w in wallets:
            policy = BudgetPolicy.from_json(w["policy"])

            daily_limit = next(
                (f"${p.limit_usd:.2f}" for p in policy.periods if p.type == "daily"),
                "—",
            )
            weekly_limit = next(
                (f"${p.limit_usd:.2f}" for p in policy.periods if p.type == "weekly"),
                "—",
            )

            status_text = "[red]⏸ PAUSED[/red]" if w["paused"] else "[green]▶ active[/green]"

            table.add_row(
                w["name"],
                w["id"][:8] + "…",
                w["created_at"][:10],
                status_text,
                daily_limit,
                weekly_limit,
                policy.fail_mode,
            )

        console.print(table)
    finally:
        ledger.close()


@wallets_app.command("create")
def create_wallet(
    name: str = typer.Argument(..., help="Wallet name"),
    daily: float | None = typer.Option(None, "--daily", help="Daily budget in USD"),
    weekly: float | None = typer.Option(None, "--weekly", help="Weekly budget in USD"),
    lifetime: float | None = typer.Option(None, "--lifetime", help="Lifetime budget in USD"),
    fail_mode: str = typer.Option("pause", "--fail-mode", help="pause|error|downgrade"),
    db: str | None = typer.Option(None, "--db", help="Database path"),
) -> None:
    """Create a new named wallet."""
    if not daily and not weekly and not lifetime:
        console.print(
            "[red]At least one budget limit is required (--daily, --weekly, or --lifetime).[/red]"
        )
        raise typer.Exit(1)

    ledger = Ledger(db_path=db)

    try:
        # Check if wallet already exists
        existing = ledger.get_wallet_by_name(name)
        if existing:
            console.print(f"[red]Wallet '{name}' already exists.[/red]")
            raise typer.Exit(1)

        periods: list[BudgetPeriod] = []
        if daily:
            periods.append(BudgetPeriod(type="daily", limit_usd=daily))
        if weekly:
            periods.append(BudgetPeriod(type="weekly", limit_usd=weekly))
        if lifetime:
            periods.append(BudgetPeriod(type="lifetime", limit_usd=lifetime))

        policy = BudgetPolicy(
            periods=periods,
            fail_mode=fail_mode,
        )

        wallet_id = ledger.create_wallet(name=name, policy_json=policy.to_json())

        console.print(f"[green]✓ Wallet '{name}' created (id: {wallet_id[:8]}…)[/green]")
        if daily:
            console.print(f"  Daily limit: ${daily:.2f}")
        if weekly:
            console.print(f"  Weekly limit: ${weekly:.2f}")
        if lifetime:
            console.print(f"  Lifetime limit: ${lifetime:.2f}")
        console.print(f"  Fail mode: {fail_mode}")
    finally:
        ledger.close()
