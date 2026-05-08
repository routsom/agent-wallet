#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up agent-wallet development environment"

# Require Python 3.11+
python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
required="3.11"
if [[ "$(printf '%s\n' "$required" "$python_version" | sort -V | head -n1)" != "$required" ]]; then
  echo "ERROR: Python $required+ required (found $python_version)" >&2
  exit 1
fi

echo "==> Python $python_version OK"

# Install in editable mode with dev extras
pip install -e ".[dev,anthropic,openai,google,telegram,discord]"

echo "==> Dependencies installed"

# Copy env example if no .env exists
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example — fill in your tokens"
fi

echo ""
echo "Setup complete. Run tests with:"
echo "  pytest tests/ -v"
echo "  mypy agent_wallet/ --strict"
echo "  ruff check agent_wallet/"
