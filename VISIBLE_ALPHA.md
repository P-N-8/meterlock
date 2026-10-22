# MeterLock tiny visible alpha v0.1

Package 0.3.0a3. Local browser UI, offline effects, no provider credentials.

## Tester experience

Start MeterLock and a browser opens on a loopback-only address. The first task
has a saved limit of three attempts. Three large counters show its limit, used
attempts and remaining attempts. Click **Run local action** three times; each
permitted action visibly completes. The next click displays **STOP / ASK HUMAN**
and never dispatches to the local HTTP target. The exhausted button stays usable
so a tester can see the refusal, rather than only a disabled control.

Create a separately named task with a finite limit, or select a saved one.
Duplicate task creation cannot reset it. Reloading the page or restarting the
process retains counters, selection and exhaustion. There is no reset button.

A sample Spend Lock card starts with $1.00 and uses the existing wallet ledger.
Its **Try $0.20 sample spend** action reserves and settles exactly $0.20 of local
demo allowance. Five succeed; the next is refused. No money moves and no model
pricing, API provider, credential or gateway is involved. The budget and all
settled/reserved balances persist. This is a separate sample wallet, not an
existing user's production/provider wallet.

Recent activity shows the latest 40 creations, allowed actions, failed actions
and refusals. Older rows stay in SQLite. An interrupted action retains an
unconfirmed history row; it never invents success or refunds a reserved attempt.
The persisted authority/ledger is authoritative, not the activity display.

## Small implementation

`meterlock.local_alpha` and one packaged HTML file supply the visible layer.
It uses Python's standard library, the unchanged Attempt Lock/HTTP adapter and
the existing SQLite wallet. No frontend/desktop framework, account, cloud server
or additional dependency was added. The existing package version labels and
CLI version display were updated; no enforcement or wallet test was changed.

Two ephemeral HTTP servers bind only to literal `127.0.0.1`: the browser UI and
one fixed internal action target. No user-supplied URL, custom header or external
action exists. The UI dispatch path calls `AttemptHTTPAction.send`, which
reserves durably before connection creation. Failures still consume attempts.
The target records a durable receipt and the committed count it observed.
UI request intents/history are separate from authority reservation: a crash can
leave unconfirmed history, but cannot grant or refund authority.

Host checks, an ephemeral UI request nonce, same-origin POSTs, no CORS allowance
and restrictive page headers prevent an unrelated website from driving the
local controls. The internal target accepts only the adapter's process marker
and an existing pending intent. These are local interface protections, not new
product authority types or a login system. A trusted storage/code owner can
still bypass the adapter, change IDs, or delete/restore storage. No hostile-code
sandbox or exactly-once delivery is claimed.

Default persistent state: `~/.meterlock/visible-alpha/alpha.db`, independent of
the gateway's ordinary wallet database and the earlier Windows test venv. Closing
the process or browser does not delete it. The sample wallet has a fixed one-year
expiry from creation; restarting does not extend that expiry or replenish funds.

## Launch

With the package installed, Python 3.11+:

```text
python -m meterlock.local_alpha
```

The prepared Windows ZIP includes the exact wheel and a small local launcher.
Extract once and double-click **Start_MeterLock.cmd**, or run its Python launcher
from Command Prompt. It creates a separate private venv, installs the verified
local wheel without downloads, then opens the browser. The UI and sample ledger
use only standard-library modules; optional gateway/provider paths are not
enabled in this dedicated UI runtime. Full regression uses the existing package
dependencies in a separate test environment. No Git or PowerShell is required.

Keep the command window open while using MeterLock; Ctrl+C stops the servers.
Relaunch to open its current local address with the same saved state. Browser
automatic opening may fall back to the printed local address if the OS has no
default browser. No public server is created.

## Verification and scope

Linux/Python 3.12.14: **148 offline tests pass**, including every pre-existing
wallet, Attempt Lock and HTTP test unchanged, plus 13 visible-layer cases.
Coverage adds only UI integration/persistence, sample-wallet exhaustion,
interrupted/failed-action display, visible-form validation and one real HTTP
proof with abrupt process restart. The proof observes three outbound action
connects total; fourth and post-restart sends cause none. Target receipts observe
committed counts 1, 2, 3. Host/nonce refusals execute no action.

Real Chromium checks cover task creation/selection, three permitted actions,
fourth refusal, sample spend, page reload, process restart, duplicate refusal,
and desktop/phone layouts. Product requests stay local, with no JavaScript
errors. The installable artifact and dedicated dependency-free UI runtime are
verified separately from a source checkout.

Penka reported the 0.3.0a2 core Windows qualification PASS on 22 October 2026:
`PASS: Windows authority-enabled candidate 0.3.0a2 (offline).`
That is accepted owner-reported evidence; its raw result JSON was not supplied
in this room. It does not establish a Windows browser/UI pass for 0.3.0a3.

This alpha is suitable for one invited, trusted tester's local/offline usability
session. Python 3.11+ and a local browser are prerequisites. Actual Windows UI
first launch remains unobserved here and can be part of that alpha session;
no further product implementation blocker is identified. It is not live-provider
qualification. No merge, release, public deployment or tester contact is made
by this gate.
