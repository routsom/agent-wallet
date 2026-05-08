"""SQLite spend ledger for agent-wallet.

Every SpendRecord is written in a single SQLite transaction.
Partial writes must never occur. Uses BEGIN IMMEDIATE for write transactions.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agent_wallet.ledger")

DEFAULT_DB_PATH = os.path.expanduser("~/.agent-wallet/ledger.db")

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS wallets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    policy TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spend_records (
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

CREATE TABLE IF NOT EXISTS kill_switch_events (
    id TEXT PRIMARY KEY,
    wallet_id TEXT NOT NULL REFERENCES wallets(id),
    triggered_at TEXT NOT NULL,
    platform TEXT NOT NULL,
    command TEXT NOT NULL,
    action TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spend_wallet_time ON spend_records(wallet_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_spend_session ON spend_records(session_id);
"""


@dataclass
class SpendRecord:
    """A single recorded API call with token usage and cost."""

    id: str
    wallet_id: str
    recorded_at: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    session_id: str | None = None
    metadata: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass
class KillSwitchEvent:
    """A kill switch event recording a pause or resume action."""

    id: str
    wallet_id: str
    triggered_at: str
    platform: str
    command: str
    action: str  # "pause" | "resume"


class Ledger:
    """SQLite-backed spend ledger.

    Thread-safe via SQLite's built-in locking.
    Uses BEGIN IMMEDIATE for all write transactions.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get("AGENT_WALLET_DB", DEFAULT_DB_PATH)

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Wallet management
    # ------------------------------------------------------------------

    def create_wallet(
        self,
        name: str,
        policy_json: str,
        wallet_id: str | None = None,
    ) -> str:
        """Create a new wallet and return its ID."""
        wid = wallet_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT INTO wallets (id, name, created_at, paused, policy) VALUES (?, ?, ?, 0, ?)",
                (wid, name, now, policy_json),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return wid

    def get_wallet(self, wallet_id: str) -> dict | None:  # type: ignore[type-arg]
        """Return wallet row as dict or None."""
        cur = self._conn.execute(
            "SELECT id, name, created_at, paused, policy FROM wallets WHERE id = ?",
            (wallet_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "paused": bool(row[3]),
            "policy": row[4],
        }

    def get_wallet_by_name(self, name: str) -> dict | None:  # type: ignore[type-arg]
        """Return wallet row by name."""
        cur = self._conn.execute(
            "SELECT id, name, created_at, paused, policy FROM wallets WHERE name = ?",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "paused": bool(row[3]),
            "policy": row[4],
        }

    def list_wallets(self) -> list[dict]:  # type: ignore[type-arg]
        """Return all wallets."""
        cur = self._conn.execute(
            "SELECT id, name, created_at, paused, policy FROM wallets ORDER BY created_at"
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "created_at": row[2],
                "paused": bool(row[3]),
                "policy": row[4],
            }
            for row in cur.fetchall()
        ]

    def pause_wallet(self, wallet_id: str) -> None:
        """Set wallet paused flag to True."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "UPDATE wallets SET paused = 1 WHERE id = ?", (wallet_id,)
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def resume_wallet(self, wallet_id: str) -> None:
        """Set wallet paused flag to False."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "UPDATE wallets SET paused = 0 WHERE id = ?", (wallet_id,)
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def is_paused(self, wallet_id: str) -> bool:
        """Check if wallet is paused."""
        cur = self._conn.execute(
            "SELECT paused FROM wallets WHERE id = ?", (wallet_id,)
        )
        row = cur.fetchone()
        return bool(row[0]) if row else False

    # ------------------------------------------------------------------
    # Spend records
    # ------------------------------------------------------------------

    def record(
        self,
        wallet_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        session_id: str | None = None,
        metadata: dict | None = None,  # type: ignore[type-arg]
    ) -> SpendRecord:
        """Write a SpendRecord atomically and return it."""
        rec = SpendRecord(
            id=str(uuid.uuid4()),
            wallet_id=wallet_id,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            session_id=session_id,
            metadata=metadata or {},
        )
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                """INSERT INTO spend_records
                   (id, wallet_id, recorded_at, provider, model,
                    input_tokens, output_tokens, cost_usd, session_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rec.id,
                    rec.wallet_id,
                    rec.recorded_at,
                    rec.provider,
                    rec.model,
                    rec.input_tokens,
                    rec.output_tokens,
                    rec.cost_usd,
                    rec.session_id,
                    json.dumps(rec.metadata),
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return rec

    def get_spend_since(
        self,
        wallet_id: str,
        since: str,
    ) -> float:
        """Return total spend (USD) for a wallet since a given ISO-8601 timestamp."""
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM spend_records "
            "WHERE wallet_id = ? AND recorded_at >= ?",
            (wallet_id, since),
        )
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    def get_total_spend(self, wallet_id: str) -> float:
        """Return total lifetime spend (USD) for a wallet."""
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM spend_records WHERE wallet_id = ?",
            (wallet_id,),
        )
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    def get_session_spend(self, wallet_id: str, session_id: str) -> float:
        """Return total spend for a specific session."""
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM spend_records "
            "WHERE wallet_id = ? AND session_id = ?",
            (wallet_id, session_id),
        )
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    def get_records(
        self,
        wallet_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[SpendRecord]:
        """Query spend records with optional filtering."""
        query = "SELECT * FROM spend_records WHERE 1=1"
        params: list = []  # type: ignore[type-arg]

        if wallet_id:
            query += " AND wallet_id = ?"
            params.append(wallet_id)
        if since:
            query += " AND recorded_at >= ?"
            params.append(since)

        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)

        cur = self._conn.execute(query, params)
        return [
            SpendRecord(
                id=row[0],
                wallet_id=row[1],
                recorded_at=row[2],
                provider=row[3],
                model=row[4],
                input_tokens=row[5],
                output_tokens=row[6],
                cost_usd=row[7],
                session_id=row[8],
                metadata=json.loads(row[9]) if row[9] else {},
            )
            for row in cur.fetchall()
        ]

    # ------------------------------------------------------------------
    # Kill switch events
    # ------------------------------------------------------------------

    def log_kill_switch_event(
        self,
        wallet_id: str,
        platform: str,
        command: str,
        action: str,
    ) -> KillSwitchEvent:
        """Log a kill switch event atomically."""
        evt = KillSwitchEvent(
            id=str(uuid.uuid4()),
            wallet_id=wallet_id,
            triggered_at=datetime.now(timezone.utc).isoformat(),
            platform=platform,
            command=command,
            action=action,
        )
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                """INSERT INTO kill_switch_events
                   (id, wallet_id, triggered_at, platform, command, action)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (evt.id, evt.wallet_id, evt.triggered_at, evt.platform, evt.command, evt.action),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return evt

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
