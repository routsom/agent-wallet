"""Unit tests for the Ledger class."""

from __future__ import annotations

import pytest
import json

from agent_wallet.ledger import Ledger, SpendRecord
from agent_wallet.policy import BudgetPolicy, BudgetPeriod


@pytest.fixture
def ledger():
    """Create an in-memory SQLite ledger."""
    db = Ledger(db_path=":memory:")
    yield db
    db.close()


class TestWalletManagement:
    def test_create_wallet(self, ledger):
        """Create a wallet and verify it exists."""
        policy = BudgetPolicy(periods=[BudgetPeriod(type="daily", limit_usd=10.0)])
        wid = ledger.create_wallet("test", policy.to_json())
        assert wid is not None

        w = ledger.get_wallet(wid)
        assert w is not None
        assert w["name"] == "test"
        assert w["paused"] is False

    def test_create_duplicate_name_raises(self, ledger):
        """Creating a wallet with a duplicate name should raise."""
        policy_json = BudgetPolicy().to_json()
        ledger.create_wallet("dupe", policy_json)

        with pytest.raises(Exception):
            ledger.create_wallet("dupe", policy_json)

    def test_get_wallet_by_name(self, ledger):
        """Get wallet by name."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("lookup", policy_json)

        w = ledger.get_wallet_by_name("lookup")
        assert w is not None
        assert w["id"] == wid

    def test_get_nonexistent_wallet(self, ledger):
        """Getting a nonexistent wallet returns None."""
        assert ledger.get_wallet("nonexistent") is None
        assert ledger.get_wallet_by_name("nonexistent") is None

    def test_list_wallets(self, ledger):
        """List all wallets."""
        policy_json = BudgetPolicy().to_json()
        ledger.create_wallet("w1", policy_json)
        ledger.create_wallet("w2", policy_json)
        ledger.create_wallet("w3", policy_json)

        wallets = ledger.list_wallets()
        assert len(wallets) == 3
        names = {w["name"] for w in wallets}
        assert names == {"w1", "w2", "w3"}


class TestPauseResume:
    def test_pause_wallet(self, ledger):
        """Pausing a wallet sets the paused flag."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("pausable", policy_json)

        assert ledger.is_paused(wid) is False
        ledger.pause_wallet(wid)
        assert ledger.is_paused(wid) is True

    def test_resume_wallet(self, ledger):
        """Resuming a wallet clears the paused flag."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("resumable", policy_json)

        ledger.pause_wallet(wid)
        assert ledger.is_paused(wid) is True

        ledger.resume_wallet(wid)
        assert ledger.is_paused(wid) is False


class TestSpendRecords:
    def test_record_spend(self, ledger):
        """Record a spend and verify it's stored."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("spender", policy_json)

        record = ledger.record(
            wallet_id=wid,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.0525,
        )

        assert record.wallet_id == wid
        assert record.provider == "anthropic"
        assert record.cost_usd == 0.0525
        assert record.input_tokens == 1000
        assert record.output_tokens == 500

    def test_get_spend_since(self, ledger):
        """get_spend_since should sum costs since a timestamp."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("time-spender", policy_json)

        ledger.record(wid, "anthropic", "claude-sonnet-4-6", 1000, 500, 1.50)
        ledger.record(wid, "openai", "gpt-4o", 2000, 1000, 2.50)

        total = ledger.get_spend_since(wid, "1970-01-01T00:00:00+00:00")
        assert abs(total - 4.00) < 0.001

    def test_get_total_spend(self, ledger):
        """get_total_spend should return lifetime total."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("lifetime-spender", policy_json)

        ledger.record(wid, "anthropic", "claude-sonnet-4-6", 1000, 500, 3.00)
        ledger.record(wid, "anthropic", "claude-sonnet-4-6", 2000, 1000, 7.00)

        total = ledger.get_total_spend(wid)
        assert abs(total - 10.00) < 0.001

    def test_get_session_spend(self, ledger):
        """get_session_spend should only count records with matching session_id."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("session-spender", policy_json)

        ledger.record(wid, "anthropic", "m1", 100, 50, 1.00, session_id="s1")
        ledger.record(wid, "anthropic", "m1", 200, 100, 2.00, session_id="s2")
        ledger.record(wid, "anthropic", "m1", 300, 150, 3.00, session_id="s1")

        assert abs(ledger.get_session_spend(wid, "s1") - 4.00) < 0.001
        assert abs(ledger.get_session_spend(wid, "s2") - 2.00) < 0.001

    def test_get_records(self, ledger):
        """get_records should return filtered records."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("query-spender", policy_json)

        for i in range(5):
            ledger.record(wid, "anthropic", f"model-{i}", 100, 50, 0.50)

        records = ledger.get_records(wallet_id=wid)
        assert len(records) == 5

    def test_model_names_stored_as_is(self, ledger):
        """Model names should be stored exactly as provided — no normalisation."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("model-test", policy_json)

        ledger.record(wid, "anthropic", "Claude-3-Sonnet-WEIRD-case", 100, 50, 1.00)

        records = ledger.get_records(wallet_id=wid)
        assert records[0].model == "Claude-3-Sonnet-WEIRD-case"

    def test_metadata_stored_as_json(self, ledger):
        """Metadata should be stored and retrieved as a dict."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("meta-test", policy_json)

        ledger.record(
            wid, "openai", "gpt-4o", 100, 50, 1.00,
            metadata={"task": "research", "agent": "bot-1"},
        )

        records = ledger.get_records(wallet_id=wid)
        assert records[0].metadata == {"task": "research", "agent": "bot-1"}


class TestKillSwitchEvents:
    def test_log_kill_switch_event(self, ledger):
        """Kill switch events should be logged."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("ks-test", policy_json)

        evt = ledger.log_kill_switch_event(
            wallet_id=wid,
            platform="telegram",
            command="STOP ks-test",
            action="pause",
        )

        assert evt.wallet_id == wid
        assert evt.platform == "telegram"
        assert evt.action == "pause"


class TestAtomicWrites:
    def test_record_is_atomic(self, ledger):
        """A successful record should be visible immediately."""
        policy_json = BudgetPolicy().to_json()
        wid = ledger.create_wallet("atomic-test", policy_json)

        ledger.record(wid, "anthropic", "claude-sonnet-4-6", 100, 50, 1.00)

        # Should be visible immediately
        total = ledger.get_total_spend(wid)
        assert total == 1.00
