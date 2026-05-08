"""Unit tests for BudgetPolicy."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from agent_wallet.policy import AutoDowngradeStep, BudgetPeriod, BudgetPolicy


class TestBudgetPolicySerialisation:
    def test_round_trip(self):
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=10.0, reset_hour=6)],
            alert_thresholds=[0.5, 0.8, 1.0],
            fail_mode="error",
            auto_downgrade=[
                AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
            ],
        )
        restored = BudgetPolicy.from_json(policy.to_json())
        assert restored.periods[0].limit_usd == 10.0
        assert restored.fail_mode == "error"
        assert restored.auto_downgrade[0].from_model == "claude-opus-4-6"

    def test_default_policy(self):
        policy = BudgetPolicy()
        assert policy.fail_mode == "pause"
        assert policy.alert_thresholds == [0.8, 1.0]


class TestPeriodStart:
    def test_daily_period_start(self):
        policy = BudgetPolicy()
        period = BudgetPeriod(type="daily", limit_usd=10.0, reset_hour=0)
        now = datetime(2025, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        start = policy.get_period_start(period, now)
        assert "2025-06-15T00:00:00" in start

    def test_daily_before_reset(self):
        policy = BudgetPolicy()
        period = BudgetPeriod(type="daily", limit_usd=10.0, reset_hour=6)
        now = datetime(2025, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
        start = policy.get_period_start(period, now)
        assert "2025-06-14T06:00:00" in start

    def test_weekly_period_start(self):
        policy = BudgetPolicy()
        period = BudgetPeriod(type="weekly", limit_usd=50.0, reset_hour=0)
        now = datetime(2025, 6, 18, 14, 30, 0, tzinfo=timezone.utc)  # Wednesday
        start = policy.get_period_start(period, now)
        assert "2025-06-16" in start

    def test_lifetime(self):
        policy = BudgetPolicy()
        period = BudgetPeriod(type="lifetime", limit_usd=100.0)
        assert "1970" in policy.get_period_start(period)


class TestAutoDowngrade:
    def test_no_downgrade_under_threshold(self):
        policy = BudgetPolicy(auto_downgrade=[
            AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
        ])
        assert policy.maybe_downgrade("claude-opus-4-6", 0.3) == "claude-opus-4-6"

    def test_downgrade_at_threshold(self):
        policy = BudgetPolicy(auto_downgrade=[
            AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
        ])
        assert policy.maybe_downgrade("claude-opus-4-6", 0.6) == "claude-sonnet-4-6"

    def test_downgrade_chain(self):
        policy = BudgetPolicy(auto_downgrade=[
            AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
            AutoDowngradeStep(0.85, "claude-sonnet-4-6", "claude-haiku-4-5-20251001", "anthropic"),
        ])
        assert policy.maybe_downgrade("claude-opus-4-6", 0.9) == "claude-haiku-4-5-20251001"

    def test_unknown_model_passthrough(self):
        policy = BudgetPolicy(auto_downgrade=[
            AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
        ])
        assert policy.maybe_downgrade("gpt-4o", 0.9) == "gpt-4o"

    def test_no_downgrade_config(self):
        policy = BudgetPolicy()
        assert policy.maybe_downgrade("claude-opus-4-6", 0.9) == "claude-opus-4-6"
