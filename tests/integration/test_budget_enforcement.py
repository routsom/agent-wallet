"""Integration tests for end-to-end budget enforcement."""

from __future__ import annotations

import os
import tempfile
import pytest
from unittest.mock import MagicMock

from agent_wallet import AgentWallet, BudgetExceededError, AutoDowngradeStep
from agent_wallet.ledger import Ledger
from agent_wallet.wallet import WalletPausedError


@pytest.fixture
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


class TestEndToEndBudget:
    def test_two_line_setup(self, tmp_db):
        """The two-line setup pattern should work."""
        wallet = AgentWallet(daily_limit_usd=5.00, db_path=tmp_db)
        assert wallet.wallet is not None
        wallet.shutdown()

    def test_budget_enforcement_flow(self, tmp_db):
        """Full flow: create wallet → spend → exceed → block."""
        aw = AgentWallet(name="e2e-test", daily_limit_usd=1.00, db_path=tmp_db)
        w = aw.wallet

        # Simulate spending
        w.record_spend("anthropic", "claude-sonnet-4-6", 1000, 500, 0.50)
        w.check_budget_or_raise()  # Should pass

        w.record_spend("anthropic", "claude-sonnet-4-6", 2000, 1000, 0.60)

        # Should now fail
        with pytest.raises(BudgetExceededError):
            w.check_budget_or_raise()

        aw.shutdown()

    def test_pause_resume_flow(self, tmp_db):
        """Full flow: pause → block → resume → allow."""
        aw = AgentWallet(name="pause-e2e", daily_limit_usd=10.00, db_path=tmp_db)
        w = aw.wallet

        w.pause()
        with pytest.raises(WalletPausedError):
            w.check_budget_or_raise()

        w.resume()
        w.check_budget_or_raise()  # Should pass now

        aw.shutdown()

    def test_disabled_mode(self, tmp_db):
        """Disabled wallet should return client unchanged."""
        aw = AgentWallet(daily_limit_usd=5.00, disabled=True, db_path=tmp_db)
        mock_client = MagicMock()
        result = aw.wrap(mock_client)
        assert result is mock_client

    def test_multi_wallet_isolation(self, tmp_db):
        """Multiple wallets should have isolated budgets."""
        aw1 = AgentWallet(name="w1", daily_limit_usd=5.00, db_path=tmp_db)
        aw2 = AgentWallet(name="w2", daily_limit_usd=5.00, db_path=tmp_db)

        aw1.wallet.record_spend("anthropic", "m", 0, 0, 4.50)
        aw2.wallet.record_spend("anthropic", "m", 0, 0, 1.00)

        # w1 should be close to limit
        assert aw1.wallet.get_budget_pct() == pytest.approx(0.9, abs=0.01)
        # w2 should be fine
        assert aw2.wallet.get_budget_pct() == pytest.approx(0.2, abs=0.01)

        aw1.shutdown()
        aw2.shutdown()

    def test_context_manager(self, tmp_db):
        """AgentWallet as context manager."""
        with AgentWallet(name="ctx", daily_limit_usd=5.00, db_path=tmp_db) as aw:
            assert aw.wallet is not None

    def test_auto_downgrade_integration(self, tmp_db):
        """Auto-downgrade should work end-to-end with interceptor."""
        aw = AgentWallet(
            name="downgrade-e2e",
            daily_limit_usd=10.00,
            auto_downgrade=[
                AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
            ],
            db_path=tmp_db,
        )
        w = aw.wallet

        # Spend 70% of budget
        w.record_spend("anthropic", "claude-opus-4-6", 0, 0, 7.00)

        # Auto-downgrade should kick in
        model = w.policy.maybe_downgrade("claude-opus-4-6", w.get_budget_pct())
        assert model == "claude-sonnet-4-6"

        aw.shutdown()
