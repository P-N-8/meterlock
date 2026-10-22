# Attempt-controlled HTTP action v0.1

22 October 2026. Integration proof; no merge, release, deployment or provider call.

## Architecture and contract

`meterlock.attempt_http.AttemptHTTPAction` is one standard-library-only adapter,
bound at construction to an existing `AttemptLock`, a stable `task_id`, an exact
`action` name and one HTTP(S) endpoint. Its frozen binding cannot be reassigned
between sends. The trusted owner must reuse those identities and the persistent
database across launches. Construction never creates or resets authority.

`send(body: bytes)` validates the body locally, then calls the unchanged
`AttemptLock.reserve(task_id, action)`. Only after a committed ALLOW does it
construct `http.client.HTTPConnection` or `HTTPSConnection`, resolve the host,
connect and make one POST. HTTPS uses the standard library's default certificate
verification. HTTPS selection was tested with a mock, not a live TLS provider.

There are no automatic retries, redirect following, environment proxies,
credential headers, provider SDKs or transport callbacks. The body is sent as
`application/octet-stream`; there is no arbitrary method/header interface.
Responses retain at most 64 KiB, encoded as base64 for JSON-safe binary data.
The connection closes after each call. The timeout bounds socket operations;
it is not a total wall-clock deadline for DNS or the entire response.

Decision fields retain the existing authority vocabulary. For example, exhaustion:

```json
{
  "outcome": "STOP",
  "next_step": "ASK_HUMAN",
  "reason": "ATTEMPT_LIMIT_EXHAUSTED",
  "dispatch_attempted": false,
  "http": null
}
```

Full decisions also include identity, attempt number and persistent state.
ALLOW means authority was granted, not that HTTP succeeded. `http.outcome`
distinguishes SUCCESS, HTTP_ERROR (including 3xx), and TRANSPORT_ERROR.
`dispatch_attempted` means transport was entered, not confirmed delivery.
Missing/unavailable authority also returns STOP before constructing transport.

Every committed grant is permanently consumed: connect failures, dropped
connections, HTTP errors, timeouts and crashes do not refund it. Local validation
errors before reservation do not consume an attempt. Partial/ambiguous delivery
is possible; the adapter does not promise exactly-once effects. A caller retry
must call `send` again and obtain another reservation. There is no reset,
extension or approval workflow; ASK_HUMAN is a machine-readable handoff signal.

## Minimal trusted-caller use

```python
from meterlock.attempt_lock import AttemptLock, AuthorityAlreadyExists
from meterlock.attempt_http import AttemptHTTPAction

# Owner-selected stable values: never generate a new ID or DB per retry/start.
lock = AttemptLock("authority.db")
try:
    lock.create("task-001", "submit-http-action", 3)
except AuthorityAlreadyExists:
    pass  # retain the existing count and limit; never replace the database
action = AttemptHTTPAction(lock, "task-001", "submit-http-action",
                           "http://127.0.0.1:8080/action")
decision = action.send(b"example payload")
```

The example assumes a separately controlled local target at that address. It
does not start a target or grant authority to call arbitrary third-party sites.
The self-contained demo below supplies its own ephemeral local target instead.

## Observed verification

Linux, Python 3.12.14: **135 tests passed**: 47 HTTP integration/adapter cases,
31 existing Attempt Lock cases and 57 existing wallet cases. All pre-existing
repository files, including wallet code, Attempt Lock, tests, dependency
declarations and old wheels, remain byte-for-byte unchanged from
`f4ced703d337e3fbb41860b4c3d6df296bad2131`.

The real HTTP demo uses a server bound only to `127.0.0.1` and separate client
processes. Audit hooks restrict client outbound connections to that exact local
port; parent outbound connections and unrelated name lookups are forbidden.
Target-side observations use a separate SQLite connection to see committed state
before recording each request. Unit tests keep the existing network-blocking
fixture unchanged and use mock transports. The local integration test runs its
bounded server/client proof in a subprocess.

| Scenario | Observed result |
| --- | --- |
| Limit 3, calls 1–3 | Three successful POSTs; target saw committed used=1,2,3 |
| Call 4 | STOP / ASK_HUMAN; zero socket connects; target stays at 3 requests |
| Fresh client interpreter, same exhausted DB | STOP / ASK_HUMAN; zero connects; target still at 3 |
| Duplicate creation with limit 999 after restart | Refused; existing max=3, used=3, exhausted=true |
| Separate limit-2 task: HTTP 503, then disconnect | Two consumed slots; next send STOP without dispatch |
| Separate limit-1 task: HTTP 307 redirect | One request; redirect not followed; next send STOP |
| Concurrent adapter calls, mocked transport | Eight calls yield only three dispatches |
| Authority table unavailable | STOP before transport construction |

Across the three independent task/action scopes, the target received exactly
six requests: three successful primary actions, two failure probes, one redirect
probe. No refusal payload and no redirected request reached it. No real API key,
paid request, external service, gateway or browser automation was used.

From the source checkout, Python 3.11+, no dependency installation for the demo:

```text
python tools/attempt_http_demo.py
```

For full regression, use the existing project test dependencies:

```text
python -m pytest -q
```

## External alpha assessment and smallest next gate

This passes the bounded integration gate and supplies the first concrete
provider-neutral action path. It is sufficient engineering evidence to prepare
a tiny, explicitly trusted-developer alpha on the tested platform. It does not
establish readiness for untrusted callers or arbitrary HTTP automation.

The smallest remaining delivery blocker is a reproducible installable candidate
qualified on the intended tester platform with this adapter and its persistent
identity/storage recipe. The existing 0.3.0a1 Windows-tested wheel predates both
authority modules; do not use that wheel to claim this integration is installed.
Windows verification of Attempt Lock/HTTP and the prior full wallet lifecycle
remains outstanding. No new wheel, release or distribution was made in this gate.

The trusted owner controls authority creation, database retention and endpoint
binding. Deleting/restoring the DB, inventing a new identity, changing the endpoint
on a newly constructed adapter or bypassing this adapter remains possible for
that owner. Task/action-to-endpoint mapping is owner configuration, not persisted
policy. Other application network paths are not intercepted. State protection,
untrusted caller access, SSRF/endpoint policy and exactly-once delivery are outside
this proof. No new permission framework or broad refactor was introduced.
