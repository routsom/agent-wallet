"""Telegram kill switch example.

Prerequisites:
    1. Create a Telegram bot via @BotFather
    2. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables
    3. pip install agent-wallet[telegram]
"""

import os
from agent_wallet import AgentWallet

# The kill switch polls Telegram every 5 seconds
# Send "STOP research-bot" to your bot to pause the agent
wallet = AgentWallet(
    name="research-bot",
    daily_limit_usd=10.00,
    kill_switch="telegram",    # Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from env
    alerts="telegram",         # Budget alerts also go to Telegram
)

print("✅ Telegram kill switch active")
print("   Send 'STOP research-bot' to pause")
print("   Send 'RESUME research-bot' to resume")
print("   Send 'STATUS' to check all wallets")

# Your agent code here...
# client = wallet.wrap(Anthropic())
# while True:
#     response = client.messages.create(...)

wallet.shutdown()
