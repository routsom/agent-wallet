"""Multi-wallet example — isolated budgets for different agents."""

from agent_wallet import AgentWallet, AutoDowngradeStep

# Research bot: $10/day with auto-downgrade
research = AgentWallet(
    name="research-bot",
    daily_limit_usd=10.00,
    auto_downgrade=[
        AutoDowngradeStep(
            at_budget_pct=0.6,
            from_model="claude-opus-4-6",
            to_model="claude-sonnet-4-6",
            provider="anthropic",
        ),
        AutoDowngradeStep(
            at_budget_pct=0.85,
            from_model="claude-sonnet-4-6",
            to_model="claude-haiku-4-5-20251001",
            provider="anthropic",
        ),
    ],
)

# Code review bot: $3/day, strict budget
reviewer = AgentWallet(
    name="code-reviewer",
    daily_limit_usd=3.00,
    fail_mode="error",
)

print("✅ Multi-wallet setup complete")
print(f"   research-bot: $10.00/day with auto-downgrade")
print(f"   code-reviewer: $3.00/day strict mode")

research.shutdown()
reviewer.shutdown()
