# MeterLock 🔒

**Your AI cannot exceed the authority you gave it.**

MeterLock is an early local developer alpha for enforcing finite authority outside an AI model.

Current release candidate: **0.3.0a3**.

It currently demonstrates two bounded controls:

- **Attempt Lock** — allow a named action only a fixed number of attempts.
- **Spend Lock** — give an AI run a finite wallet and refuse further spend when the allowance is exhausted.

When authority runs out, MeterLock returns **STOP / ASK HUMAN** instead of relying on the model to remember a rule.

## See it hold

The tiny visible alpha runs as a local browser app and needs no provider key or real money.

The default Attempt Lock starts at three attempts:

1. run the local action three times;
2. watch Used reach 3 and Remaining reach 0;
3. try a fourth time;
4. MeterLock refuses it before dispatch with **STOP / ASK HUMAN**;
5. restart MeterLock and the exhausted state is still there.

The sample Spend Lock starts at $1.00 and simulates $0.20 spends. Five are allowed; the sixth is refused.

Recent activity shows what MeterLock allowed and what it stopped.

## Windows alpha

Requires Python 3.11+ with `venv` / `pip` and a browser.

The Windows-observed tester bundle is designed to be extracted completely, then launched from Command Prompt inside the extracted folder:

```cmd
py -3 -I launch_meterlock.py
```

If the `py` launcher is unavailable:

```cmd
python -I launch_meterlock.py
```

The launcher verifies the exact bundled wheel, creates a separate private runtime without downloads, and opens the browser UI.

Do **not** disable Windows Smart App Control. An earlier unsigned `.cmd` convenience launcher was blocked during the first real Windows UI session, so the corrected tester path uses Python directly. A future consumer-style Windows distribution should use an appropriately signed launcher or installer.

## What is enforced today

### Attempt Lock

- immutable configured attempt limit for a task/action identity;
- atomic reservation before action dispatch;
- exhaustion refuses execution with `STOP` / `ASK_HUMAN`;
- failures and interrupted actions still consume committed attempts;
- exhaustion survives process restart;
- recreating the same authority cannot reset it.

The current HTTP adapter demonstrates this boundary against a fixed local HTTP target. It is an adapter, not a universal sandbox.

### Spend Lock

The existing wallet path reserves budget before a supported provider request, reconciles against actual usage, and supports pause, resume and permanent revoke.

The visible alpha uses a local sample wallet so the control can be understood without credentials or paid requests.

## Verification

Current 0.3.0a3 evidence:

- **148 offline tests passed** against the installed wheel;
- all 135 predecessor wallet / Attempt Lock / HTTP tests remain unchanged;
- Chromium desktop and phone-width UI checks passed;
- real Windows visible-alpha session passed the core user story:
  - 3 allowed attempts → fourth refused;
  - restart → still exhausted;
  - $1.00 sample wallet → sixth $0.20 spend refused;
  - restart → exhausted spend state persisted;
  - Recent activity persisted.

See [VISIBLE_ALPHA.md](VISIBLE_ALPHA.md) for the detailed alpha contract and verification boundary.

## Trust boundary

This is **alpha software**, not a hostile-code sandbox.

A trusted machine/storage owner can bypass the wrapper, alter or restore local state, choose a different identity or data directory, or modify the code. MeterLock currently enforces the path that is routed through it; it does not claim to make arbitrary local code unable to escape.

No authenticated human-approval system or exactly-once delivery guarantee exists yet.

## Provider path

The repository also contains the earlier OpenAI-compatible local gateway / finite-wallet work. That path is separate from the no-credential visible demo and should still be treated as experimental developer-alpha functionality.

Do not use production credentials, sensitive workloads or meaningful spend limits.

## Status

**0.3.0a3 release candidate:** local visible authority alpha proven on Windows and ready for launch preparation.

Not yet claimed:

- production security;
- signed consumer installer;
- hosted SaaS;
- accounts or teams;
- billing;
- broad provider compatibility;
- arbitrary external-action sandboxing.

The product question is deliberately simple:

> **Can an AI be given finite authority that remains enforceable even when the model itself keeps trying?**
