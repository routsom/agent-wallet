"""Basic Anthropic example with agent-wallet budget enforcement."""

from agent_wallet import AgentWallet

# Two-line setup — your agent can never spend more than $5/day
wallet = AgentWallet(daily_limit_usd=5.00)

# Uncomment below when you have the anthropic package installed:
# from anthropic import Anthropic
# client = wallet.wrap(Anthropic())
#
# response = client.messages.create(
#     model="claude-sonnet-4-6",
#     max_tokens=1024,
#     messages=[{"role": "user", "content": "Hello!"}],
# )
# print(response.content[0].text)

print("✅ AgentWallet initialized with $5.00/day limit")
print(f"   Wallet ID: {wallet.wallet.wallet_id[:8]}...")
print(f"   Session: {wallet.wallet.session_id[:8]}...")
wallet.shutdown()
