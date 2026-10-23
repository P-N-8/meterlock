# Attempt Lock v0.1 — offline proof

22 October 2026. Development gate only; no released artifact or gateway feature.

## Smallest design

`meterlock.attempt_lock.AttemptLock` is a standard-library-only companion to the
wallet implementation. It uses one SQLite table in a caller-selected persistent
database: a unique `(task_id, action)` identity, immutable `max_attempts`, and a
monotonic `used` counter. It does not change or import spend-lock enforcement.

`create(task_id, action, max_attempts)` creates authority once. Repeating the
same creation raises `AuthorityAlreadyExists`, including after restarting.
`reserve(...)` increments the counter inside `BEGIN IMMEDIATE` and commits with
SQLite synchronous FULL before returning a grant. `run(..., callback)` invokes
the callback only after that durable grant. Every call is one attempt: failures
consume their reservation, and a crash between reservation and execution may
consume an unused slot. There is no refund, reset or automatic limit extension.

Decisions are JSON-compatible dictionaries. A refusal has:

```json
{
  "outcome": "STOP",
  "next_step": "ASK_HUMAN",
  "reason": "ATTEMPT_LIMIT_EXHAUSTED",
  "executed": false
}
```

Actual decisions additionally include the task/action identity, state and attempt
number; refusal has no attempt number. Reasons distinguish missing authority and
unavailable state. ASK_HUMAN is a machine-readable handoff signal, not an approval
workflow or permission to reset the counter. A database error refuses execution.

## Observed offline verification

Linux/Python 3.12, 22 October 2026: **88 tests passed**, comprising **31 Attempt
Lock tests and all 57 pre-existing wallet tests unchanged**. The existing runtime
modules, wallet test files, dependency declaration and published wheel are
unchanged from base `d3f8007551e98b7b2364f3589cb8d3d9b65fe8df`.

The standalone proof launches two separate Python processes against the same
temporary database and records simulated effects in a file:

| Observation | Result |
| --- | --- |
| Attempts 1, 2 and 3 | ALLOW; exactly three simulated effects |
| Attempt 4 | STOP / ASK_HUMAN; no effect |
| New interpreter, existing exhausted authority | STOP / ASK_HUMAN; still no effect |
| Re-create same task/action after restart | Refused; counter stays at 3 |

Additional tests cover independent concurrent processes and threads (only three
grants), an abrupt process exit immediately after reservation, failed actions,
failed database updates/rollback, missing state, task/action scoping and zero
limits. Tests block network connections; demonstration processes block socket
operations with an audit hook. No gateway, real API key or provider request is
used. Legacy HTTP tests use mocked transport and synthetic placeholders.

Run the self-contained proof from the source checkout, with Python 3.11+:

```text
python tools/attempt_lock_demo.py
```

It needs no dependency installation or external service. For the full regression
suite, use the project's existing development/test dependencies:

```text
python -m pytest -q
```

This gate was not run on Windows. It does not supersede outstanding Windows
wallet lifecycle or live provider qualification.

## Suitability and boundary before an external alpha

The proof supports Attempt Lock as the first non-financial, consumable authority
primitive: durable reservation, dispatch only after permission, deterministic
exhaustion and explicit escalation generalize directly from spend enforcement.
No generic permission framework or other permission types were added.

The caller and storage owner are trusted in v0.1. An owner who deletes/restores
the database, selects a new database or invents a fresh task ID can start fresh
authority. A callback can also perform work outside this wrapper. This module
does not sandbox hostile code or provide authenticated human approval. It limits
grants, not successful effects or exactly-once delivery.

Before advertising enforcement in a small external alpha, select one concrete
action adapter and ensure every retry uses this reservation boundary with a
stable owner-controlled task/action ID and persistent storage. Define who may
create new authority. Qualify process restart and concurrent use on the supported
platform; Windows support remains unverified for this extension. These integration
and trust-boundary decisions are the next blockers, rather than additional
permission types, UI or billing. No merge, release or deployment was performed.
