# Security — external alpha

MeterLock v0.2.0 is an experimental local developer alpha, not production-security software.

## Test safely

- Use a dedicated temporary OpenAI API key.
- Put that key in a provider project with a very small hard spend limit.
- Use tiny MeterLock wallets.
- Do not use production workloads or sensitive prompts.
- Revoke the upstream provider key after testing.
- Never post an OpenAI key or `mlk_live_...` key in a GitHub issue, screenshot, chat, or log.

## Current data handling

The local SQLite ledger stores:

- lock ID and label;
- budget, spent, reserved and remaining accounting state;
- expiry / pause / revoke state;
- SHA-256 digest of the scoped MeterLock key;
- reservation records.

MeterLock does not intentionally persist:

- the upstream OpenAI API key;
- plaintext scoped MeterLock keys;
- prompt bodies;
- response bodies.

Prompts and responses necessarily transit the local gateway process in memory in order to forward requests.

## Failure policy

If a provider call fails after MeterLock has authorised/dispatched it and the actual cost cannot be known safely, the alpha conservatively treats the full reservation as spent rather than returning uncertain money to the wallet.

## Reporting

For non-sensitive bugs, open a GitHub issue with reproduction steps.

For a potentially sensitive security problem, do **not** publish secrets or exploit details in a public issue. Open only a minimal issue stating that you need a private security contact path.

No bug bounty is offered for this alpha.