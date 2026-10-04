# MeterLock 🔒

**Finite wallets for AI agents.**

MeterLock is an early developer alpha for one simple problem:

> Give this AI run a fixed amount of money. When the allowance is gone, further provider generation is refused.

MeterLock sits in the request path, reserves budget **before** forwarding a generation request, then reconciles the reservation against actual usage. The current alpha runs locally on your machine and supports OpenAI only.

## Why this exists

Provider-level monthly budgets are useful, but they answer a different question.

MeterLock is aimed at:

- one agent;
- one unattended run;
- one explicit wallet;
- one expiry;
- pause / resume / permanent revoke.

The control object is the **agent/run**, not the whole provider account or project.

## External alpha v0.2.0

Current boundary:

- local gateway only;
- OpenAI only;
- model: `gpt-5.6-luna`;
- plain-text Responses requests only;
- explicit `max_output_tokens` from 16 to 500;
- persistent local SQLite ledger;
- scoped `mlk_live_...` key per wallet;
- upstream OpenAI key is held by the running process and is not written to the MeterLock database;
- no prompt/response persistence by MeterLock.

This is **not production software**. Use a dedicated low-limit OpenAI project/key and tiny test wallets.

## Fast tester path

Requires Python 3.11+.

Install the alpha wheel:

```powershell
python -m pip install https://raw.githubusercontent.com/P-N-8/meterlock/main/dist/meterlock_alpha-0.2.0-py3-none-any.whl
```

Start MeterLock:

```powershell
meterlock start
```

Paste your temporary OpenAI API key into the hidden prompt.

In a second terminal, create a tiny wallet:

```powershell
meterlock create --label first-test --budget 0.01 --minutes 30
```

MeterLock returns:

- a Lock ID;
- a one-time scoped `mlk_live_...` key;
- the local base URL `http://127.0.0.1:8787/v1`.

Point an OpenAI-compatible client at that base URL and use the scoped MeterLock key instead of the upstream OpenAI key.

Control the wallet:

```powershell
meterlock list
meterlock status LOCK_ID
meterlock pause LOCK_ID
meterlock resume LOCK_ID
meterlock revoke LOCK_ID
```

Revocation is permanent.

For the exact tester task and what feedback we need, see [ALPHA_TEST.md](ALPHA_TEST.md).

## What MeterLock does not do yet

No hosted SaaS. No accounts. No Stripe. No Anthropic. No teams. No routing. No anomaly detection. No historical provider billing. No tool-call support. No production-security claim.

The point of this alpha is to answer one commercial question:

**Can a developer install this, give one AI run a finite wallet, and find that useful without bespoke help from us?**

## Privacy boundary

MeterLock's local ledger stores wallet/accounting state and SHA-256 digests of scoped MeterLock keys. The upstream OpenAI key is not stored in that database. Prompts and responses transit the local gateway but are not intentionally persisted by MeterLock.

Read [SECURITY.md](SECURITY.md) before testing.

## Status

Stage A: hard concurrent authorization proof — PASS.

Stage B: scoped wallet lifecycle (spend / pause / resume / revoke / restart persistence) — PASS live.

Stage C: external developer alpha — **ready for independent testing; not yet externally validated**.

---

**Alpha warning:** spend real money only with tiny limits and a disposable/dedicated provider key.