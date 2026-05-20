"""Cost calculation from pricing manifest.

Loads pricing data from the bundled YAML or a custom path via AGENT_WALLET_PRICING.
Model names are used as-is (no normalisation) with a fallback to 0.0 for unknown models.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger("agent_wallet.pricing")

_BUNDLED_PRICING = Path(__file__).parent / "pricing.yaml"


@lru_cache(maxsize=1)
def _load_pricing() -> dict[str, Any]:
    """Load and cache the pricing manifest."""
    pricing_path = os.environ.get("AGENT_WALLET_PRICING", str(_BUNDLED_PRICING))
    path = Path(pricing_path)

    if not path.exists():
        logger.warning(f"Pricing file not found: {path}. Using empty pricing.")
        return {}

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return {}

    return cast(dict[str, Any], data.get("providers", {}))


def calculate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate the USD cost for a given API call.

    Returns 0.0 for unknown provider/model combinations (with a warning).
    Model names are matched as-is — no normalisation.
    """
    pricing = _load_pricing()

    provider_data = pricing.get(provider)
    if not provider_data:
        logger.warning(f"Unknown provider for pricing: {provider}")
        return 0.0

    models = provider_data.get("models", {})

    # Try exact model match first
    model_pricing = models.get(model)

    if not model_pricing:
        # Try the default pricing for this provider (e.g. ollama)
        model_pricing = provider_data.get("default")

    if not model_pricing:
        logger.warning(
            f"Unknown model for pricing: {provider}/{model}. Cost will be 0.0."
        )
        return 0.0

    input_cost = (input_tokens / 1_000_000) * float(model_pricing.get("input_per_1m", 0.0))
    output_cost = (output_tokens / 1_000_000) * float(model_pricing.get("output_per_1m", 0.0))

    return round(input_cost + output_cost, 8)


def get_known_models(provider: str) -> list[str]:
    """Return list of known model names for a provider."""
    pricing = _load_pricing()
    provider_data = pricing.get(provider, {})
    return list(provider_data.get("models", {}).keys())
