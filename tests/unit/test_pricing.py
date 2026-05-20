"""Unit tests for agent_wallet/pricing.py."""

from __future__ import annotations

import os

import pytest
import yaml

from agent_wallet.pricing import _load_pricing, calculate_cost, get_known_models


# _load_pricing is lru_cache'd — clear it between tests that manipulate env vars.
@pytest.fixture(autouse=True)
def clear_pricing_cache():
    _load_pricing.cache_clear()
    yield
    _load_pricing.cache_clear()


class TestCalculateCost:
    def test_known_anthropic_model(self):
        """claude-sonnet-4-6: $3/1M input, $15/1M output."""
        cost = calculate_cost("anthropic", "claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert abs(cost - 18.0) < 1e-6

    def test_known_openai_model(self):
        """gpt-4o: $2.50/1M input, $10/1M output."""
        cost = calculate_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
        assert abs(cost - 12.5) < 1e-6

    def test_small_token_count(self):
        """100 input + 50 output tokens for claude-sonnet-4-6."""
        cost = calculate_cost("anthropic", "claude-sonnet-4-6", 100, 50)
        expected = (100 / 1_000_000) * 3.0 + (50 / 1_000_000) * 15.0
        assert abs(cost - expected) < 1e-9

    def test_zero_tokens_returns_zero(self):
        cost = calculate_cost("anthropic", "claude-sonnet-4-6", 0, 0)
        assert cost == 0.0

    def test_unknown_provider_returns_zero(self):
        cost = calculate_cost("unknown-provider", "some-model", 1000, 500)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self):
        cost = calculate_cost("anthropic", "claude-nonexistent-9999", 1000, 500)
        assert cost == 0.0

    def test_ollama_default_pricing_zero(self):
        """Ollama has a default entry with 0.00 rates."""
        cost = calculate_cost("ollama", "llama3", 100_000, 50_000)
        assert cost == 0.0

    def test_result_is_float(self):
        cost = calculate_cost("openai", "gpt-4o-mini", 500, 200)
        assert isinstance(cost, float)

    def test_cost_rounded_to_8_decimal_places(self):
        """Result should be rounded to 8 decimal places."""
        cost = calculate_cost("anthropic", "claude-haiku-4-5-20251001", 1, 1)
        assert cost == round(cost, 8)

    def test_custom_pricing_file(self, tmp_path):
        """AGENT_WALLET_PRICING env var overrides the bundled pricing."""
        custom = {
            "providers": {
                "myprovider": {
                    "models": {
                        "mymodel": {
                            "input_per_1m": 1.0,
                            "output_per_1m": 2.0,
                        }
                    }
                }
            }
        }
        p = tmp_path / "custom_pricing.yaml"
        p.write_text(yaml.dump(custom))

        os.environ["AGENT_WALLET_PRICING"] = str(p)
        try:
            _load_pricing.cache_clear()
            cost = calculate_cost("myprovider", "mymodel", 1_000_000, 1_000_000)
            assert abs(cost - 3.0) < 1e-6
        finally:
            del os.environ["AGENT_WALLET_PRICING"]

    def test_missing_pricing_file_returns_zero(self, tmp_path):
        """A missing pricing file should return 0.0 cost (empty pricing)."""
        os.environ["AGENT_WALLET_PRICING"] = str(tmp_path / "nonexistent.yaml")
        try:
            _load_pricing.cache_clear()
            cost = calculate_cost("anthropic", "claude-sonnet-4-6", 1000, 500)
            assert cost == 0.0
        finally:
            del os.environ["AGENT_WALLET_PRICING"]

    def test_invalid_yaml_content_returns_zero(self, tmp_path):
        """A YAML file that does not parse to a dict should return 0.0 cost."""
        p = tmp_path / "bad_pricing.yaml"
        p.write_text("- just\n- a\n- list\n")
        os.environ["AGENT_WALLET_PRICING"] = str(p)
        try:
            _load_pricing.cache_clear()
            cost = calculate_cost("anthropic", "claude-sonnet-4-6", 1000, 500)
            assert cost == 0.0
        finally:
            del os.environ["AGENT_WALLET_PRICING"]


class TestGetKnownModels:
    def test_anthropic_models_nonempty(self):
        models = get_known_models("anthropic")
        assert len(models) > 0

    def test_openai_models_nonempty(self):
        models = get_known_models("openai")
        assert len(models) > 0

    def test_google_models_nonempty(self):
        models = get_known_models("google")
        assert len(models) > 0

    def test_anthropic_contains_sonnet(self):
        models = get_known_models("anthropic")
        assert "claude-sonnet-4-6" in models

    def test_openai_contains_gpt4o(self):
        models = get_known_models("openai")
        assert "gpt-4o" in models

    def test_unknown_provider_returns_empty_list(self):
        models = get_known_models("nonexistent-provider")
        assert models == []

    def test_returns_list_of_strings(self):
        models = get_known_models("anthropic")
        assert isinstance(models, list)
        assert all(isinstance(m, str) for m in models)
