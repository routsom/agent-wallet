"""CLI command: agent-wallet history"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from agent_wallet.ledger import Ledger, SpendRecord

console = Console()


def history(
    wallet: str | None = typer.Option(None, "--wallet", "-w", help="Wallet name"),
    days: int = typer.Option(7, "--days", "-d", help="Number of days to show"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
    db: str | None = typer.Option(None, "--db", help="Database path"),
) -> None:
    """Show spend history. Groups by day and model."""
    ledger = Ledger(db_path=db)

    try:
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        # Find wallet ID if name provided
        wallet_id = None
        if wallet:
            w = ledger.get_wallet_by_name(wallet)
            if not w:
                console.print(f"[red]Wallet '{wallet}' not found.[/red]")
                raise typer.Exit(1)
            wallet_id = w["id"]

        records = ledger.get_records(wallet_id=wallet_id, since=since, limit=1000)

        if not records:
            console.print("[yellow]No spend records found.[/yellow]")
            return

        if format == "json":
            _output_json(records)
        elif format == "csv":
            _output_csv(records)
        else:
            _output_table(records, days)
    finally:
        ledger.close()


def _output_table(records: list[SpendRecord], days: int) -> None:
    """Output spend records as a rich table grouped by day and model."""
    # Group by day and model
    groups: dict[str, dict[str, dict[str, Any]]] = {}

    for r in records:
        day = r.recorded_at[:10]  # YYYY-MM-DD
        key = f"{r.provider}/{r.model}"

        if day not in groups:
            groups[day] = {}
        if key not in groups[day]:
            groups[day][key] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }

        groups[day][key]["calls"] += 1
        groups[day][key]["input_tokens"] += r.input_tokens
        groups[day][key]["output_tokens"] += r.output_tokens
        groups[day][key]["cost_usd"] += r.cost_usd

    table = Table(title=f"📊 Spend History (last {days} days)", show_lines=True)
    table.add_column("Date", style="cyan")
    table.add_column("Model", style="bold")
    table.add_column("Calls", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Cost", justify="right", style="green")

    for day in sorted(groups.keys(), reverse=True):
        day_total = 0.0
        for model, stats in sorted(groups[day].items()):
            table.add_row(
                day,
                model,
                str(stats["calls"]),
                f"{stats['input_tokens']:,}",
                f"{stats['output_tokens']:,}",
                f"${stats['cost_usd']:.6f}",
            )
            day_total += stats["cost_usd"]
        table.add_row(day, "[bold]TOTAL[/bold]", "", "", "", f"[bold]${day_total:.6f}[/bold]")

    console.print(table)


def _output_json(records: list[SpendRecord]) -> None:
    """Output records as JSON."""
    data = [
        {
            "id": r.id,
            "wallet_id": r.wallet_id,
            "recorded_at": r.recorded_at,
            "provider": r.provider,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": r.cost_usd,
            "session_id": r.session_id,
        }
        for r in records
    ]
    console.print(json.dumps(data, indent=2))


def _output_csv(records: list[SpendRecord]) -> None:
    """Output records as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "wallet_id", "recorded_at", "provider", "model",
        "input_tokens", "output_tokens", "cost_usd", "session_id",
    ])
    for r in records:
        writer.writerow([
            r.id, r.wallet_id, r.recorded_at, r.provider, r.model,
            r.input_tokens, r.output_tokens, r.cost_usd, r.session_id,
        ])
    console.print(output.getvalue())
