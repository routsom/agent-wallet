"""Unit tests for the Wallet class."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from agent_wallet.killswitch.base import KillSwitchBase
from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy, AutoDowngradeStep
from agent_wallet.wallet import Wallet, BudgetExceededError, WalletPausedError


class ConcreteKillSwitch(KillSwitchBase):
    """Minimal concrete kill switch for testing KillSwitchBase."""

    platform_name = "test"

    def __init__(self, ledger: Ledger) -> None:
        super().__init__(command="STOP", poll_interval=1, ledger=ledger)
        self.replies: list[str] = []

    def poll(self) -> None:
        pass

    def reply(self, text: str) -> None:
        self.replies.append(text)


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


class TestSessionAndLifetimePeriods:
    def test_session_period_under_budget(self, ledger):
        """Session period budget check passes when under limit."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="session", limit_usd=5.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="session-test", policy=policy, ledger=ledger)
        wallet.check_budget_or_raise()  # Should not raise

    def test_session_period_exceeded(self, ledger):
        """Session period budget check raises when exceeded."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="session", limit_usd=1.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="session-exceed", policy=policy, ledger=ledger)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=2.00,
            session_id=wallet.session_id,
        )
        with pytest.raises(BudgetExceededError):
            wallet.check_budget_or_raise()

    def test_lifetime_period_under_budget(self, ledger):
        """Lifetime period budget check passes when under limit."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="lifetime", limit_usd=100.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="lifetime-test", policy=policy, ledger=ledger)
        wallet.check_budget_or_raise()  # Should not raise

    def test_lifetime_period_exceeded(self, ledger):
        """Lifetime period budget check raises when exceeded."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="lifetime", limit_usd=1.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="lifetime-exceed", policy=policy, ledger=ledger)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=2.00,
        )
        with pytest.raises(BudgetExceededError):
            wallet.check_budget_or_raise()

    def test_budget_pct_session_period(self, ledger):
        """get_budget_pct works for session period."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="session", limit_usd=10.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="pct-session", policy=policy, ledger=ledger)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=5.00,
            session_id=wallet.session_id,
        )
        assert abs(wallet.get_budget_pct() - 0.5) < 0.001

    def test_budget_pct_lifetime_period(self, ledger):
        """get_budget_pct works for lifetime period."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="lifetime", limit_usd=10.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="pct-lifetime", policy=policy, ledger=ledger)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=4.00,
        )
        assert abs(wallet.get_budget_pct() - 0.4) < 0.001

    def test_budget_pct_zero_limit_skipped(self, ledger):
        """Periods with zero limit are skipped in pct calculation."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=0.0)],
            fail_mode="pause",
        )
        wallet = Wallet(name="pct-zero", policy=policy, ledger=ledger)
        assert wallet.get_budget_pct() == 0.0


class TestKillSwitch:
    def test_kill_switch_started_on_init(self, ledger, basic_policy):
        """Kill switch should be started when wallet is created."""
        from unittest.mock import MagicMock

        mock_ks = MagicMock()
        wallet = Wallet(
            name="ks-test", policy=basic_policy, ledger=ledger, kill_switch=mock_ks
        )
        mock_ks.start.assert_called_once_with(wallet)

    def test_shutdown_stops_kill_switch(self, ledger, basic_policy):
        """shutdown() should stop the kill switch."""
        from unittest.mock import MagicMock

        mock_ks = MagicMock()
        wallet = Wallet(
            name="ks-shutdown", policy=basic_policy, ledger=ledger, kill_switch=mock_ks
        )
        wallet.shutdown()
        mock_ks.stop.assert_called_once()

    def test_shutdown_without_kill_switch(self, wallet):
        """shutdown() with no kill switch should not raise."""
        wallet.shutdown()

    def test_context_manager_calls_shutdown(self, ledger, basic_policy):
        """Context manager __exit__ should call shutdown."""
        from unittest.mock import MagicMock

        mock_ks = MagicMock()
        with Wallet(
            name="ks-ctx", policy=basic_policy, ledger=ledger, kill_switch=mock_ks
        ):
            pass
        mock_ks.stop.assert_called_once()


class TestAlerts:
    def test_maybe_alert_no_alerts_configured(self, wallet):
        """maybe_alert does nothing when no alerts configured."""
        wallet.maybe_alert()  # Should not raise

    def test_maybe_alert_fires_at_threshold(self, ledger):
        """maybe_alert fires alert when budget threshold crossed."""
        from unittest.mock import MagicMock

        mock_alert = MagicMock()
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
            alert_thresholds=[0.8],
            fail_mode="pause",
        )
        wallet = Wallet(
            name="alert-test", policy=policy, ledger=ledger, alerts=[mock_alert]
        )
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=9.00,
        )
        wallet.maybe_alert()
        mock_alert.send.assert_called_once()
        call_kwargs = mock_alert.send.call_args.kwargs
        assert call_kwargs["wallet_name"] == "alert-test"
        assert call_kwargs["threshold_pct"] == 0.8

    def test_maybe_alert_not_fired_below_threshold(self, ledger):
        """maybe_alert does not fire when below threshold."""
        from unittest.mock import MagicMock

        mock_alert = MagicMock()
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
            alert_thresholds=[0.8],
            fail_mode="pause",
        )
        wallet = Wallet(
            name="alert-below", policy=policy, ledger=ledger, alerts=[mock_alert]
        )
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=5.00,
        )
        wallet.maybe_alert()
        mock_alert.send.assert_not_called()

    def test_maybe_alert_fires_only_once_per_threshold(self, ledger):
        """maybe_alert should not re-fire for the same threshold."""
        from unittest.mock import MagicMock

        mock_alert = MagicMock()
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
            alert_thresholds=[0.8],
            fail_mode="pause",
        )
        wallet = Wallet(
            name="alert-once", policy=policy, ledger=ledger, alerts=[mock_alert]
        )
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=9.00,
        )
        wallet.maybe_alert()
        wallet.maybe_alert()  # Second call should not re-fire
        mock_alert.send.assert_called_once()

    def test_maybe_alert_swallows_send_errors(self, ledger):
        """Alert send errors should be logged and swallowed."""
        from unittest.mock import MagicMock

        mock_alert = MagicMock()
        mock_alert.send.side_effect = RuntimeError("network error")
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
            alert_thresholds=[0.8],
            fail_mode="pause",
        )
        wallet = Wallet(
            name="alert-err", policy=policy, ledger=ledger, alerts=[mock_alert]
        )
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=9.00,
        )
        wallet.maybe_alert()  # Should NOT raise

    def test_maybe_alert_async_runs(self, ledger, basic_policy):
        """maybe_alert_async runs in background thread without blocking."""
        import time

        wallet = Wallet(name="async-alert", policy=basic_policy, ledger=ledger)
        wallet.maybe_alert_async()
        time.sleep(0.05)  # Let background thread complete


class TestGetTightestPeriodInfo:
    def test_returns_tightest_period(self, ledger):
        """_get_tightest_period_info returns the most utilised period."""
        policy = BudgetPolicy(
            periods=[
                BudgetPeriod(type="daily", limit_usd=10.00),
                BudgetPeriod(type="lifetime", limit_usd=100.00),
            ],
            fail_mode="pause",
        )
        wallet = Wallet(name="tightest-test", policy=policy, ledger=ledger)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=8.00,  # 80% of daily, 8% of lifetime
        )
        info = wallet._get_tightest_period_info()
        assert info["period_type"] == "daily"
        assert abs(info["spent"] - 8.00) < 0.001
        assert info["limit"] == 10.00

    def test_empty_periods_returns_default(self, ledger):
        """_get_tightest_period_info returns unknown when no valid periods."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=0.0)],
            fail_mode="pause",
        )
        wallet = Wallet(name="tightest-empty", policy=policy, ledger=ledger)
        info = wallet._get_tightest_period_info()
        assert info["period_type"] == "unknown"

    def test_session_period_in_tightest(self, ledger):
        """_get_tightest_period_info handles session period type."""
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="session", limit_usd=10.00)],
            fail_mode="pause",
        )
        wallet = Wallet(name="tightest-session", policy=policy, ledger=ledger)
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=6.00,
            session_id=wallet.session_id,
        )
        info = wallet._get_tightest_period_info()
        assert info["period_type"] == "session"


class TestGetTodaySpend:
    def test_get_today_spend_zero(self, wallet):
        """get_today_spend returns 0 with no spend."""
        assert wallet.get_today_spend() == 0.0

    def test_get_today_spend_with_records(self, wallet, ledger):
        """get_today_spend returns today's total."""
        ledger.record(
            wallet_id=wallet.wallet_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=3.50,
        )
        assert abs(wallet.get_today_spend() - 3.50) < 0.001


class TestKillSwitchOnMessage:
    def test_stop_named_wallet(self, ledger, basic_policy):
        """STOP <name> pauses the wallet (name must be uppercase-safe)."""
        w = Wallet(name="MYBOT", policy=basic_policy, ledger=ledger)
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("STOP MYBOT")
        assert ledger.is_paused(w.wallet_id)
        assert any("paused" in r for r in ks.replies)

    def test_stop_unknown_wallet(self, ledger):
        """STOP <unknown> sends not-found reply."""
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("STOP no-such-wallet")
        assert any("Unknown wallet" in r for r in ks.replies)

    def test_resume_named_wallet(self, ledger, basic_policy):
        """RESUME <name> resumes a paused wallet (name must be uppercase-safe)."""
        w = Wallet(name="MYBOT2", policy=basic_policy, ledger=ledger)
        ledger.pause_wallet(w.wallet_id)
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("RESUME MYBOT2")
        assert not ledger.is_paused(w.wallet_id)
        assert any("resumed" in r.lower() for r in ks.replies)

    def test_resume_unknown_wallet(self, ledger):
        """RESUME <unknown> sends not-found reply."""
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("RESUME no-such-wallet")
        assert any("Unknown wallet" in r for r in ks.replies)

    def test_status_command(self, ledger, wallet):
        """STATUS replies with wallet statuses."""
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("STATUS")
        assert len(ks.replies) > 0
        assert any("test-wallet" in r for r in ks.replies)

    def test_status_no_wallets(self, ledger):
        """STATUS with no wallets replies accordingly."""
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("STATUS")
        assert any("No wallets" in r for r in ks.replies)

    def test_bare_stop_with_wallet(self, ledger, basic_policy, wallet):
        """Bare STOP pauses the associated wallet."""
        ks = ConcreteKillSwitch(ledger)
        ks._wallet = wallet
        ks.on_message("STOP")
        assert ledger.is_paused(wallet.wallet_id)

    def test_unknown_command_ignored(self, ledger):
        """Unrecognised messages produce no reply."""
        ks = ConcreteKillSwitch(ledger)
        ks.on_message("HELLO WORLD")
        assert len(ks.replies) == 0
