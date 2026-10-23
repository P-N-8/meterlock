# MeterLock 0.3.0a3 — visible authority alpha

Local browser UI, offline effects, no provider credentials.

## Product story

MeterLock demonstrates finite external authority with two existing controls:

- **Attempt Lock** — a named action may execute only a configured number of times.
- **Spend Lock** — a finite wallet refuses additional spend once exhausted.

The visible alpha makes the rule observable: authority is consumed before action, exhaustion returns **STOP / ASK HUMAN**, and the exhausted state survives restart.

## Tester experience

The first task has a saved limit of three attempts. Three large counters show **Attempt limit / Used / Remaining**.

Click **Run local action** three times. Each permitted action completes. The fourth click displays **STOP / ASK HUMAN** and does not dispatch to the local HTTP target.

A separately named authority can be created with a finite limit. Duplicate creation cannot reset an existing authority. Reloading the page or restarting the process retains counters, selection and exhaustion. There is no reset/refund control.

The sample Spend Lock starts at $1.00 and uses the existing wallet ledger. **Try $0.20 sample spend** reserves and settles exactly $0.20 of local demo allowance. Five succeed; the sixth is refused. No real money or provider request is involved.

Recent activity shows task creation plus allowed, blocked, failed or unconfirmed actions. Counter/ledger state is authoritative.

## Implementation boundary

`meterlock.local_alpha` and one packaged HTML file supply the visible layer.

Two ephemeral HTTP servers bind only to literal `127.0.0.1`: the browser UI and one fixed internal action target. The UI dispatch path calls the existing `AttemptHTTPAction.send`, which reserves durably before connection creation. Failures still consume attempts.

No frontend framework, desktop framework, account, cloud service, arbitrary endpoint field, provider credential or new authority type is introduced.

The current alpha is a trusted-owner local tool, not a hostile-code sandbox. A storage/code owner can bypass the adapter, change identities, or delete/restore state.

## Windows launch — observed path

Requires Python 3.11+ with venv/pip and a browser.

Extract the Windows-observed bundle completely. In the extracted `visible-alpha-0.3.0a3` folder, open Command Prompt and run:

```cmd
py -3 -I launch_meterlock.py
```

If `py` is unavailable:

```cmd
python -I launch_meterlock.py
```

The launcher verifies the exact bundled wheel, prepares a separate private runtime without downloads, and opens the local browser UI.

Do **not** disable Windows Smart App Control. The earlier unsigned `Start_MeterLock.cmd` convenience launcher was blocked on the first real Windows session; the Python path above worked normally. A signed launcher/installer is a later consumer-distribution requirement.

Default persistent state:

```text
%USERPROFILE%\.meterlock\visible-alpha\alpha.db
```

## Verification

Package **0.3.0a3**.

Installed regression:

- 57 wallet cases
- 31 Attempt Lock cases
- 47 attempt-controlled HTTP cases
- 13 visible-layer cases
- **148 passed, 0 failed**

Chromium desktop/mobile checks cover creation/selection, three permitted actions, fourth STOP, sample spend, reload, process restart, post-restart STOP, duplicate refusal and phone-width layout.

Observed on Penka's Windows machine on 22 October 2026:

- visible alpha opened successfully via the Python launcher;
- Attempt Lock: 3 / 0 / 3 → three successful actions → 3 / 3 / 0;
- fourth action: **STOP / ASK HUMAN**;
- restart: Attempt Lock remained 3 / 3 / 0;
- Spend Lock: five $0.20 sample spends reached $1.00 used / $0.00 remaining / Exhausted;
- sixth spend: **STOP / ASK HUMAN**;
- restart: exhausted spend state persisted;
- Recent activity persisted and showed the allowed and blocked actions.

No live provider compatibility is claimed by this visible-alpha proof.
