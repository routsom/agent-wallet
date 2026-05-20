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


class TestGoogleInterceptor:
    def test_records_spend_with_usage_metadata(self, wallet, ledger):
        from agent_wallet.interceptors.google import WrappedGenerativeModel

        mock_model = MagicMock()
        usage = MagicMock()
        usage.prompt_token_count = 800
        usage.candidates_token_count = 400
        mock_response = MagicMock()
        mock_response.usage_metadata = usage
        mock_model.generate_content.return_value = mock_response

        wrapped_model = WrappedGenerativeModel(mock_model, wallet, "gemini-2.0-flash")
        resp = wrapped_model.generate_content("Hello")

        assert resp == mock_response
        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].provider == "google"

    def test_records_spend_without_usage_metadata(self, wallet, ledger):
        from agent_wallet.interceptors.google import WrappedGenerativeModel

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.usage_metadata = None
        mock_model.generate_content.return_value = mock_response

        wrapped_model = WrappedGenerativeModel(mock_model, wallet, "gemini-2.0-flash")
        wrapped_model.generate_content("Hello")

        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 0

    def test_blocks_when_budget_exceeded(self, wallet, ledger):
        from agent_wallet.interceptors.google import WrappedGenerativeModel

        ledger.record(wallet.wallet_id, "google", "m", 0, 0, 10.01)
        mock_model = MagicMock()
        wrapped_model = WrappedGenerativeModel(mock_model, wallet, "gemini-2.0-flash")

        with pytest.raises(BudgetExceededError):
            wrapped_model.generate_content("Hello")
        mock_model.generate_content.assert_not_called()

    def test_wrapped_google_creates_model(self, wallet):
        from agent_wallet.interceptors.google import WrappedGenerativeModel, WrappedGoogle

        mock_client = MagicMock()
        wrapped = WrappedGoogle(mock_client, wallet)
        model = wrapped.GenerativeModel("gemini-2.0-flash")
        assert isinstance(model, WrappedGenerativeModel)
        mock_client.GenerativeModel.assert_called_once_with("gemini-2.0-flash")

    def test_passthrough_attributes(self, wallet):
        from agent_wallet.interceptors.google import WrappedGoogle

        mock_client = MagicMock()
        mock_client.some_attr = "value"
        wrapped = WrappedGoogle(mock_client, wallet)
        assert wrapped.some_attr == "value"


class TestOllamaInterceptor:
    def test_chat_with_dict_response(self, wallet, ledger):
        from agent_wallet.interceptors.ollama import WrappedOllama

        mock_client = MagicMock()
        mock_client.chat.return_value = {"prompt_eval_count": 500, "eval_count": 200}
        wrapped = WrappedOllama(mock_client, wallet)
        resp = wrapped.chat(model="llama3", messages=[])

        assert resp["eval_count"] == 200
        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].provider == "ollama"
        assert records[0].input_tokens == 500

    def test_chat_with_attr_response(self, wallet, ledger):
        from agent_wallet.interceptors.ollama import WrappedOllama

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.prompt_eval_count = 300
        mock_response.eval_count = 150
        mock_client.chat.return_value = mock_response
        wrapped = WrappedOllama(mock_client, wallet)
        wrapped.chat(model="llama3", messages=[])

        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].input_tokens == 300

    def test_generate_with_dict_response(self, wallet, ledger):
        from agent_wallet.interceptors.ollama import WrappedOllama

        mock_client = MagicMock()
        mock_client.generate.return_value = {"prompt_eval_count": 100, "eval_count": 50}
        wrapped = WrappedOllama(mock_client, wallet)
        wrapped.generate(model="llama3", prompt="Hello")

        records = ledger.get_records(wallet_id=wallet.wallet_id)
        assert len(records) == 1
        assert records[0].output_tokens == 50

    def test_blocks_when_budget_exceeded(self, wallet, ledger):
        from agent_wallet.interceptors.ollama import WrappedOllama

        ledger.record(wallet.wallet_id, "ollama", "m", 0, 0, 10.01)
        mock_client = MagicMock()
        wrapped = WrappedOllama(mock_client, wallet)

        with pytest.raises(BudgetExceededError):
            wrapped.chat(model="llama3", messages=[])
        mock_client.chat.assert_not_called()

    def test_passthrough_attributes(self, wallet):
        from agent_wallet.interceptors.ollama import WrappedOllama

        mock_client = MagicMock()
        mock_client.host = "http://localhost:11434"
        wrapped = WrappedOllama(mock_client, wallet)
        assert wrapped.host == "http://localhost:11434"
