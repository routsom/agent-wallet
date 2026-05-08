"""Unit tests for provider interceptors."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from agent_wallet.ledger import Ledger
from agent_wallet.policy import BudgetPeriod, BudgetPolicy, AutoDowngradeStep
from agent_wallet.wallet import Wallet, BudgetExceededError
from agent_wallet.interceptors.anthropic import WrappedAnthropic
from agent_wallet.interceptors.openai import WrappedOpenAI


@pytest.fixture
def ledger():
    db = Ledger(db_path=":memory:")
    yield db
    db.close()


@pytest.fixture
def policy():
    return BudgetPolicy(
        periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
        fail_mode="pause",
    )


@pytest.fixture
def wallet(ledger, policy):
    return Wallet(name="interceptor-test", policy=policy, ledger=ledger)


class TestAnthropicInterceptor:
    def test_records_spend_on_success(self, wallet, ledger):
        mock_client = MagicMock()
        usage = MagicMock()
        usage.input_tokens = 1000
        usage.output_tokens = 500
        mock_response = MagicMock()
        mock_response.usage = usage
        mock_client.messages.create.return_value = mock_response

        wrapped = WrappedAnthropic(mock_client, wallet)
        resp = wrapped.messages.create(model="claude-sonnet-4-6", messages=[])

        assert resp == mock_response
        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].provider == "anthropic"
        assert records[0].model == "claude-sonnet-4-6"

    def test_blocks_when_budget_exceeded(self, wallet, ledger):
        ledger.record(wallet.wallet_id, "anthropic", "m", 0, 0, 10.01)
        mock_client = MagicMock()
        wrapped = WrappedAnthropic(mock_client, wallet)

        with pytest.raises(BudgetExceededError):
            wrapped.messages.create(model="claude-sonnet-4-6", messages=[])
        mock_client.messages.create.assert_not_called()

    def test_auto_downgrade_model(self, ledger):
        policy = BudgetPolicy(
            periods=[BudgetPeriod(type="daily", limit_usd=10.00)],
            auto_downgrade=[
                AutoDowngradeStep(0.6, "claude-opus-4-6", "claude-sonnet-4-6", "anthropic"),
            ],
        )
        w = Wallet(name="downgrade-int", policy=policy, ledger=ledger)
        ledger.record(w.wallet_id, "anthropic", "m", 0, 0, 7.00)

        mock_client = MagicMock()
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        mock_client.messages.create.return_value = MagicMock(usage=usage)

        wrapped = WrappedAnthropic(mock_client, w)
        wrapped.messages.create(model="claude-opus-4-6", messages=[])

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"

    def test_passthrough_attributes(self, wallet):
        mock_client = MagicMock()
        mock_client.api_key = "test-key"
        wrapped = WrappedAnthropic(mock_client, wallet)
        assert wrapped.api_key == "test-key"


class TestOpenAIInterceptor:
    def test_records_spend_on_success(self, wallet, ledger):
        mock_client = MagicMock()
        usage = MagicMock()
        usage.prompt_tokens = 1000
        usage.completion_tokens = 500
        mock_response = MagicMock()
        mock_response.usage = usage
        mock_client.chat.completions.create.return_value = mock_response

        wrapped = WrappedOpenAI(mock_client, wallet)
        resp = wrapped.chat.completions.create(model="gpt-4o", messages=[])

        assert resp == mock_response
        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].provider == "openai"

    def test_blocks_when_budget_exceeded(self, wallet, ledger):
        ledger.record(wallet.wallet_id, "openai", "m", 0, 0, 10.01)
        mock_client = MagicMock()
        wrapped = WrappedOpenAI(mock_client, wallet)

        with pytest.raises(BudgetExceededError):
            wrapped.chat.completions.create(model="gpt-4o", messages=[])
        mock_client.chat.completions.create.assert_not_called()
