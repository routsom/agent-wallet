"""Unit tests for the Wallet class."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy, AutoDowngradeStep
from agent_wallet.wallet import Wallet, BudgetExceededError, WalletPausedError


@pytest.fixture
def ledger():
    """Create an in-memory SQLite ledger for testing."""
    db = Ledger(db_path=":memory:")
    yield db
    db.close()


@pytest.fixture
def basic_policy():
    """Create a basic daily budget policy."""
    return BudgetPolicy(
        periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
        alert_thresholds=[0.8, 1.0],
        fail_mode="pause",
    )


@pytest.fixture
def wallet(ledger, basic_policy):
    """Create a test wallet."""
    return Wallet(name="test-wallet", policy=basic_policy, ledger=ledger)


class TestWalletCreation:
    def test_wallet_created_in_ledger(self, wallet, ledger):
        """Wallet should be registered in the ledger on creation."""
        w = ledger.get_wallet_by_name("test-wallet")
        assert w is not None
        assert w["name"] == "test-wallet"
        assert w["paused"] is False

    def test_wallet_reuses_existing(self, ledger, basic_policy):
        """Creating a wallet with the same name should reuse the existing one."""
        w1 = Wallet(name="existing", policy=basic_policy, ledger=ledger)
        w2 = Wallet(name="existing", policy=basic_policy, ledger=ledger)
        assert w1.wallet_id == w2.wallet_id

    def test_wallet_has_session_id(self, wallet):
        """Each wallet should have a unique session ID."""
        assert wallet.session_id is not None
        assert len(wallet.session_id) > 0


class TestBudgetEnforcement:
    def test_check_passes_under_budget(self, wallet):
        """Budget check should pass when under limit."""
        wallet.check_budget_or_raise()  # Should not raise

    def test_check_fails_over_budget(self, wallet, ledger):
        """Budget check should raise when over limit."""
        # Spend $10.01 (over $10 limit)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=100000,
            output_tokens=10000,
            cost_usd=10.01,
        )

        with pytest.raises(BudgetExceededError) as exc_info:
            wallet.check_budget_or_raise()

        assert "test-wallet" in str(exc_info.value)
        assert exc_info.value.spent >= 10.01

    def test_check_fails_at_exact_limit(self, wallet, ledger):
        """Budget check should raise when exactly at limit."""
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=100000,
            output_tokens=10000,
            cost_usd=10.00,
        )

        with pytest.raises(BudgetExceededError):
            wallet.check_budget_or_raise()

    def test_multiple_spends_accumulate(self, wallet, ledger):
        """Multiple small spends should accumulate toward the limit."""
        for _ in range(5):
            ledger.record(
                wallet_id=wallet.wallet_id,
                provider="openai",
                model="gpt-4o",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=2.00,
            )

        # $10.00 total = at limit
        with pytest.raises(BudgetExceededError):
            wallet.check_budget_or_raise()


class TestPausedWallet:
    def test_paused_wallet_raises(self, wallet, ledger):
        """A paused wallet should raise WalletPausedError."""
        ledger.pause_wallet(wallet.wallet_id)

        with pytest.raises(WalletPausedError) as exc_info:
            wallet.check_budget_or_raise()

        assert "test-wallet" in str(exc_info.value)

    def test_resumed_wallet_passes(self, wallet, ledger):
        """A resumed wallet should pass budget checks."""
        ledger.pause_wallet(wallet.wallet_id)
        ledger.resume_wallet(wallet.wallet_id)
        wallet.check_budget_or_raise()  # Should not raise

    def test_pause_property(self, wallet, ledger):
        """The paused property should reflect the ledger state."""
        assert wallet.paused is False
        wallet.pause()
        assert wallet.paused is True
        wallet.resume()
        assert wallet.paused is False


class TestBudgetPercentage:
    def test_zero_spend_zero_pct(self, wallet):
        """No spend should result in 0% budget usage."""
        assert wallet.get_budget_pct() == 0.0

    def test_half_budget_50pct(self, wallet, ledger):
        """$5 of $10 limit should be 50%."""
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=50000,
            output_tokens=5000,
            cost_usd=5.00,
        )
        assert abs(wallet.get_budget_pct() - 0.5) < 0.001


class TestRecordSpend:
    def test_record_spend_success(self, wallet, ledger):
        """record_spend should write to the ledger."""
        wallet.record_spend(
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )
        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].cost_usd == 0.05

    def test_record_spend_non_blocking_on_error(self, wallet, ledger, monkeypatch):
        """record_spend should log warning and continue on ledger errors."""
        def fail_record(*args, **kwargs):
            raise RuntimeError("DB write failed")

        monkeypatch.setattr(ledger, "record", fail_record)

        # Should NOT raise
        wallet.record_spend(
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )


class TestDowngradeMode:
    def test_downgrade_fail_mode_no_raise(self, ledger):
        """With fail_mode=downgrade, budget exceeded should not raise."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=1.00)],
            fail_mode="downgrade",
        )
        wallet = Wallet(name="downgrade-test", policy=policy, ledger=ledger)

        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=100000,
            output_tokens=10000,
            cost_usd=1.50,
        )

        # Should NOT raise with fail_mode=downgrade
        wallet.check_budget_or_raise()


class TestContextManager:
    def test_context_manager(self, ledger, basic_policy):
        """Wallet should work as a context manager."""
        with Wallet(name="ctx-test", policy=basic_policy, ledger=ledger) as w:
            assert w.name == "ctx-test"
