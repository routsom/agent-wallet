// TypeScript example (placeholder — TS SDK in development)
// This shows the intended API design for the TypeScript package.

import { AgentWallet } from 'agent-wallet';
import Anthropic from '@anthropic-ai/sdk';

const wallet = new AgentWallet({
  dailyLimitUsd: 5.00,
  killSwitch: 'telegram',
});

const client = wallet.wrap(new Anthropic());

const response = await client.messages.create({
  model: 'claude-sonnet-4-6',
  max_tokens: 1024,
  messages: [{ role: 'user', content: 'Hello!' }],
});

console.log(response.content[0].text);

wallet.shutdown();
