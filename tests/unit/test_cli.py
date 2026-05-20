"""Unit tests for CLI commands and AgentWallet public API."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agent_wallet.cli.main import app
from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy


runner = CliRunner()


@pytest.fixture
def db_path(tmp_path):
    """Provide a temp SQLite path for each test."""
    return str(tmp_path / "test.db")


@pytest.fixture
def populated_db(db_path):
    """A ledger with one wallet and one spend record."""
    ledger = Ledger(db_path=db_path)
    policy = BudgetPolicy(
        periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
        fail_mode="pause",
    )
    wid = ledger.create_wallet(name="test-wallet", policy_json=policy.to_json())
    ledger.record(
        wallet_id=wid,
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=2.50,
    )
    ledger.close()
    return db_path


class TestStatusCommand:
    def test_status_all_wallets(self, populated_db):
        result = runner.invoke(app, ["status", "--db", populated_db])
        assert result.exit_code == 0
        assert "test-wa" in result.output  # Rich truncates long names

    def test_status_specific_wallet(self, populated_db):
        result = runner.invoke(app, ["status", "--wallet", "test-wallet", "--db", populated_db])
        assert result.exit_code == 0
        assert "test-wa" in result.output  # Rich truncates long names

    def test_status_unknown_wallet(self, populated_db):
        result = runner.invoke(app, ["status", "--wallet", "no-such-wallet", "--db", populated_db])
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_status_empty_db(self, db_path):
        result = runner.invoke(app, ["status", "--db", db_path])
        assert result.exit_code == 0


class TestPauseResumeCommands:
    def test_pause_wallet(self, populated_db):
        result = runner.invoke(app, ["pause", "test-wallet", "--db", populated_db])
        assert result.exit_code == 0
        ledger = Ledger(db_path=populated_db)
        w = ledger.get_wallet_by_name("test-wallet")
        assert w is not None
        assert ledger.is_paused(w["id"])
        ledger.close()

    def test_resume_wallet(self, populated_db):
        runner.invoke(app, ["pause", "test-wallet", "--db", populated_db])
        result = runner.invoke(app, ["resume", "test-wallet", "--db", populated_db])
        assert result.exit_code == 0
        ledger = Ledger(db_path=populated_db)
        w = ledger.get_wallet_by_name("test-wallet")
        assert w is not None
        assert not ledger.is_paused(w["id"])
        ledger.close()

    def test_pause_unknown_wallet(self, populated_db):
        result = runner.invoke(app, ["pause", "no-such-wallet", "--db", populated_db])
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_resume_unknown_wallet(self, populated_db):
        result = runner.invoke(app, ["resume", "no-such-wallet", "--db", populated_db])
        assert result.exit_code != 0 or "not found" in result.output.lower()


class TestHistoryCommand:
    def test_history_table(self, populated_db):
        result = runner.invoke(app, ["history", "--db", populated_db])
        assert result.exit_code == 0

    def test_history_json(self, populated_db):
        result = runner.invoke(app, ["history", "--format", "json", "--db", populated_db])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        assert data[0]["provider"] == "anthropic"

    def test_history_csv(self, populated_db):
        result = runner.invoke(app, ["history", "--format", "csv", "--db", populated_db])
        assert result.exit_code == 0
        assert "provider" in result.output

    def test_history_specific_wallet(self, populated_db):
        result = runner.invoke(
            app, ["history", "--wallet", "test-wallet", "--db", populated_db]
        )
        assert result.exit_code == 0

    def test_history_days_filter(self, populated_db):
        result = runner.invoke(app, ["history", "--days", "7", "--db", populated_db])
        assert result.exit_code == 0


class TestWalletsSubcommand:
    def test_wallets_list(self, populated_db):
        result = runner.invoke(app, ["wallets", "list", "--db", populated_db])
        assert result.exit_code == 0
        assert "test-wa" in result.output  # Rich truncates long names

    def test_wallets_list_empty(self, db_path):
        result = runner.invoke(app, ["wallets", "list", "--db", db_path])
        assert result.exit_code == 0

    def test_wallets_create_daily(self, db_path):
        result = runner.invoke(
            app, ["wallets", "create", "new-wallet", "--daily", "5.00", "--db", db_path]
        )
        assert result.exit_code == 0
        ledger = Ledger(db_path=db_path)
        assert ledger.get_wallet_by_name("new-wallet") is not None
        ledger.close()

    def test_wallets_create_no_budget_fails(self, db_path):
        result = runner.invoke(app, ["wallets", "create", "bad-wallet", "--db", db_path])
        assert result.exit_code != 0

    def test_wallets_create_multiple_periods(self, db_path):
        result = runner.invoke(
            app,
            [
                "wallets", "create", "multi-wallet",
                "--daily", "5.00",
                "--weekly", "20.00",
                "--db", db_path,
            ],
        )
        assert result.exit_code == 0


class TestAgentWalletAPI:
    def test_disabled_via_flag(self):
        from agent_wallet import AgentWallet

        aw = AgentWallet(daily_limit_usd=5.00, disabled=True)
        assert aw.wallet is None

    def test_disabled_via_env(self, monkeypatch):
        from agent_wallet import AgentWallet

        monkeypatch.setenv("AGENT_WALLET_DISABLED", "1")
        aw = AgentWallet(daily_limit_usd=5.00)
        assert aw.wallet is None

    def test_wrap_returns_client_when_disabled(self):
        from unittest.mock import MagicMock

        from agent_wallet import AgentWallet

        aw = AgentWallet(daily_limit_usd=5.00, disabled=True)
        mock_client = MagicMock()
        assert aw.wrap(mock_client) is mock_client

    def test_basic_creation(self, tmp_path):
        from agent_wallet import AgentWallet

        db = str(tmp_path / "aw.db")
        aw = AgentWallet(name="api-test", daily_limit_usd=10.00, db_path=db)
        assert aw.wallet is not None
        assert aw.wallet.name == "api-test"
        aw.shutdown()

    def test_wrap_anthropic(self, tmp_path):
        from unittest.mock import MagicMock

        from agent_wallet import AgentWallet
        from agent_wallet.interceptors.anthropic import WrappedAnthropic

        db = str(tmp_path / "aw.db")
        aw = AgentWallet(name="wrap-test", daily_limit_usd=10.00, db_path=db)
        mock_client = MagicMock()
        mock_client.__class__.__name__ = "Anthropic"
        mock_client.__class__.__module__ = "anthropic"
        wrapped = aw.wrap(mock_client)
        assert isinstance(wrapped, WrappedAnthropic)
        aw.shutdown()

    def test_wrap_openai(self, tmp_path):
        from unittest.mock import MagicMock

        from agent_wallet import AgentWallet
        from agent_wallet.interceptors.openai import WrappedOpenAI

        db = str(tmp_path / "aw.db")
        aw = AgentWallet(name="wrap-oai", daily_limit_usd=10.00, db_path=db)
        mock_client = MagicMock()
        mock_client.__class__.__name__ = "OpenAI"
        mock_client.__class__.__module__ = "openai"
        wrapped = aw.wrap(mock_client)
        assert isinstance(wrapped, WrappedOpenAI)
        aw.shutdown()

    def test_wrap_unsupported_raises(self, tmp_path):
        from unittest.mock import MagicMock

        from agent_wallet import AgentWallet

        db = str(tmp_path / "aw.db")
        aw = AgentWallet(name="wrap-bad", daily_limit_usd=10.00, db_path=db)
        mock_client = MagicMock()
        mock_client.__class__.__name__ = "SomeOtherClient"
        mock_client.__class__.__module__ = "some_other_module"
        with pytest.raises(ValueError, match="Unsupported client type"):
            aw.wrap(mock_client)
        aw.shutdown()

    def test_context_manager(self, tmp_path):
        from agent_wallet import AgentWallet

        db = str(tmp_path / "aw.db")
        with AgentWallet(name="ctx-aw", daily_limit_usd=10.00, db_path=db) as aw:
            assert aw.wallet is not None

    def test_all_period_types(self, tmp_path):
        from agent_wallet import AgentWallet

        db = str(tmp_path / "periods.db")
        aw = AgentWallet(
            name="periods-test",
            daily_limit_usd=5.00,
            weekly_limit_usd=20.00,
            session_limit_usd=2.00,
            lifetime_limit_usd=100.00,
            db_path=db,
        )
        assert aw.wallet is not None
        assert len(aw.wallet.policy.periods) == 4
        aw.shutdown()
