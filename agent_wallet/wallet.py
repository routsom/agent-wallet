"""Core Wallet class for agent-wallet.

The Wallet is the central coordination point. It owns the ledger reference,
policy, and provides the pre-flight / post-flight checks that interceptors call.

This module is synchronous by design — async wrappers live in interceptors.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy

if TYPE_CHECKING:
    from agent_wallet.alerts.base import AlertBase
    from agent_wallet.killswitch.base import KillSwitchBase

logger = logging.getLogger("agent_wallet")


class BudgetExceededError(Exception):
    """Raised when a wallet's budget has been exceeded."""

    def __init__(self, wallet_name: str, spent: float, limit: float, period: str) -> None:
        self.wallet_name = wallet_name
        self.spent = spent
        self.limit = limit
        self.period = period
        super().__init__(
            f"Budget exceeded for wallet '{wallet_name}': "
            f"${spent:.4f} / ${limit:.2f} ({period})"
        )


class WalletPausedError(Exception):
    """Raised when a call is attempted on a paused wallet."""

    def __init__(self, wallet_name: str) -> None:
        self.wallet_name = wallet_name
        super().__init__(
            f"Wallet '{wallet_name}' is paused. Send RESUME to un-pause."
        )


class Wallet:
    """A named budget-constrained wallet.

    Each wallet has an isolated budget, spend history, and can be independently
    paused/resumed via the kill switch or CLI.
    """

    def __init__(
        self,
        name: str,
        policy: BudgetPolicy,
        ledger: Ledger,
        session_id: str | None = None,
        alerts: list[AlertBase] | None = None,
        kill_switch: KillSwitchBase | None = None,
    ) -> None:
        self.name = name
        self.policy = policy
        self.ledger = ledger
        self.session_id = session_id or str(uuid.uuid4())
        self._alerts: list[AlertBase] = alerts or []
        self._kill_switch = kill_switch
        self._alerted_thresholds: set[float] = set()
        self._lock = threading.Lock()

        # Register wallet in the ledger if it doesn't exist
        existing = ledger.get_wallet_by_name(name)
        if existing:
            self.wallet_id = existing["id"]
        else:
            self.wallet_id = ledger.create_wallet(
                name=name,
                policy_json=policy.to_json(),
            )

        # Start kill switch polling if configured
        if self._kill_switch:
            self._kill_switch.start(self)

    def check_budget_or_raise(self, now: datetime | None = None) -> None:
        """Pre-flight check: raise if wallet is paused or budget exceeded.

        This is called before every provider API call by interceptors.
        """
        # Check if paused (from kill switch or manual pause)
        if self.ledger.is_paused(self.wallet_id):
            raise WalletPausedError(self.name)

        now = now or datetime.now(UTC)

        # Check each budget period
        for period in self.policy.periods:
            if period.type == "session":
                spent = self.ledger.get_session_spend(self.wallet_id, self.session_id)
            elif period.type == "lifetime":
                spent = self.ledger.get_total_spend(self.wallet_id)
            else:
                since = self.policy.get_period_start(period, now)
                spent = self.ledger.get_spend_since(self.wallet_id, since)

            if spent >= period.limit_usd:
                if self.policy.fail_mode == "downgrade":
                    # Don't raise — the interceptor will handle downgrading
                    logger.warning(
                        f"Budget exceeded for '{self.name}' ({period.type}): "
                        f"${spent:.4f} / ${period.limit_usd:.2f}. "
                        f"fail_mode=downgrade, continuing."
                    )
                else:
                    raise BudgetExceededError(
                        self.name, spent, period.limit_usd, period.type
                    )

    def get_budget_pct(self, now: datetime | None = None) -> float:
        """Return the highest budget utilisation percentage across all periods.

        Used by auto-downgrade to decide which model to use.
        """
        now = now or datetime.now(UTC)
        max_pct = 0.0

        for period in self.policy.periods:
            if period.limit_usd <= 0:
                continue

            if period.type == "session":
                spent = self.ledger.get_session_spend(self.wallet_id, self.session_id)
            elif period.type == "lifetime":
                spent = self.ledger.get_total_spend(self.wallet_id)
            else:
                since = self.policy.get_period_start(period, now)
                spent = self.ledger.get_spend_since(self.wallet_id, since)

            pct = spent / period.limit_usd
            max_pct = max(max_pct, pct)

        return max_pct

    def record_spend(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        metadata: dict | None = None,  # type: ignore[type-arg]
    ) -> None:
        """Record a spend event. Non-blocking on errors (logs warning)."""
        try:
            self.ledger.record(
                wallet_id=self.wallet_id,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                session_id=self.session_id,
                metadata=metadata,
            )
        except Exception as e:
            logger.warning(f"agent-wallet: ledger write failed: {e}")
            # Call continues — ledger errors are non-fatal

    def maybe_alert(self, now: datetime | None = None) -> None:
        """Post-flight check: fire alerts if threshold crossed.

        Non-blocking — errors are logged and swallowed.
        """
        if not self._alerts:
            return

        budget_pct = self.get_budget_pct(now)

        for threshold in self.policy.alert_thresholds:
            if budget_pct >= threshold and threshold not in self._alerted_thresholds:
                self._alerted_thresholds.add(threshold)

                # Find the tightest period for reporting
                spent_info = self._get_tightest_period_info(now)

                for alert in self._alerts:
                    try:
                        alert.send(
                            wallet_name=self.name,
                            threshold_pct=threshold,
                            budget_pct=budget_pct,
                            spent_usd=spent_info["spent"],
                            limit_usd=spent_info["limit"],
                            period_type=spent_info["period_type"],
                        )
                    except Exception as e:
                        logger.warning(f"agent-wallet: alert send failed: {e}")

    def maybe_alert_async(self, now: datetime | None = None) -> None:
        """Fire alerts in a background thread (non-blocking)."""
        thread = threading.Thread(
            target=self.maybe_alert,
            args=(now,),
            daemon=True,
        )
        thread.start()

    def _get_tightest_period_info(
        self, now: datetime | None = None
    ) -> dict[str, Any]:
        """Get the period with the highest utilisation for alert reporting."""
        now = now or datetime.now(UTC)
        best: dict[str, Any] = {"spent": 0.0, "limit": 0.0, "period_type": "unknown", "pct": 0.0}

        for period in self.policy.periods:
            if period.limit_usd <= 0:
                continue

            if period.type == "session":
                spent = self.ledger.get_session_spend(self.wallet_id, self.session_id)
            elif period.type == "lifetime":
                spent = self.ledger.get_total_spend(self.wallet_id)
            else:
                since = self.policy.get_period_start(period, now)
                spent = self.ledger.get_spend_since(self.wallet_id, since)

            pct = spent / period.limit_usd
            if pct > best["pct"]:
                best = {
                    "spent": spent,
                    "limit": period.limit_usd,
                    "period_type": period.type,
                    "pct": pct,
                }

        return best

    def pause(self) -> None:
        """Manually pause this wallet."""
        self.ledger.pause_wallet(self.wallet_id)

    def resume(self) -> None:
        """Manually resume this wallet."""
        self.ledger.resume_wallet(self.wallet_id)

    @property
    def paused(self) -> bool:
        """Check if this wallet is currently paused."""
        return self.ledger.is_paused(self.wallet_id)

    def get_today_spend(self) -> float:
        """Get today's total spend."""
        period = BudgetPeriod(type="daily", limit_usd=0, reset_hour=0)
        since = self.policy.get_period_start(period)
        return self.ledger.get_spend_since(self.wallet_id, since)

    def shutdown(self) -> None:
        """Stop kill switch polling and clean up."""
        if self._kill_switch:
            self._kill_switch.stop()

    def __enter__(self) -> Wallet:
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()
