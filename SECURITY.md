# Security — MeterLock alpha

MeterLock 0.3.0a3 is experimental local developer-alpha software, not production-security software.

## Current visible-alpha boundary

The visible alpha:

- binds its browser UI and internal sample action target to `127.0.0.1`;
- uses persisted local SQLite state;
- has no account/login;
- needs no provider key;
- performs no paid provider request;
- exposes no arbitrary external endpoint field in the normal UI.

Host checks, same-origin requests and a local request nonce reduce accidental/unrelated browser driving of the local UI. They are interface protections, not a hostile-code sandbox.

## Trusted-owner limitation

A machine/storage/code owner can still bypass MeterLock by modifying code, changing identities or data directories, or deleting/restoring local state. MeterLock enforces actions that are actually routed through its control path.

A failed or interrupted action may still consume an already committed attempt. There is no exactly-once delivery guarantee and no authenticated human-approval system.

## Existing provider gateway

The repository also contains the earlier experimental provider gateway / finite-wallet path.

If testing that path:

- use a dedicated temporary provider key;
- use the provider's own small hard project limit;
- use tiny MeterLock wallets;
- avoid production workloads and sensitive prompts;
- revoke temporary credentials after testing;
- never post provider keys or scoped MeterLock keys in issues, screenshots, chats or logs.

MeterLock does not intentionally persist upstream provider keys, plaintext scoped MeterLock keys, prompts or response bodies in its wallet ledger.

## Failure policy

Where cost or authority has been committed before an external action and the final outcome cannot be known safely, the alpha fails conservatively rather than silently refunding uncertain authority.

## Reporting

For non-sensitive bugs, open a GitHub issue with reproduction steps.

For a potentially sensitive security problem, do **not** publish secrets or exploit details in a public issue. Open only a minimal issue stating that you need a private security contact path.

No bug bounty is offered for this alpha.
