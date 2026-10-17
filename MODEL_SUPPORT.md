# Multi-model candidate 0.3.0a1 — not released

Prepared 17 October 2026. This local candidate adds `gpt-6-luna` and `gpt-6-sol`
alongside `gpt-5.6-luna`. Exact IDs only; unknown models and aliases are refused
before any provider call. There is no silent model substitution.

The published 0.2.0 wheel is unchanged and remains Luna-only. Nothing in this
candidate has been live-qualified against OpenAI or tested on Windows.

## Request boundary

One global OpenAI Standard `/v1/responses` request with nonempty plain text,
explicit `max_output_tokens` 16–500, `reasoning.effort: none`, and `store: false`.
Standard is explicitly selected with `service_tier: default`; a missing or
different returned tier causes conservative uncertain settlement. No tools,
images, streaming, extra request fields, regional endpoints, pro execution,
fine-tunes, or user-defined pricing. All models spend the same scoped wallet.

## Pricing basis

USD per million tokens, global Standard, checked 17 October 2026:

| Model | Input | Cached input | Cache writes | Output |
| --- | ---: | ---: | ---: | ---: |
| gpt-5.6-luna | 0.20 | 0.02 | 0.25 | 1.20 |
| gpt-6-luna | 0.10 | 0.01 | 0.125 | 0.50 |
| gpt-6-sol | 2.00 | 0.20 | 2.50 | 10.00 |

For more than 272,000 input tokens, input/cache rates double and output rates
increase by 1.5 for the full request. Input tokens are partitioned into ordinary,
cached and cache-write tokens, not charged twice. Arithmetic uses integer
nanodollars throughout.
Both cache counters must be present as non-negative integers in returned usage;
missing counters are treated as uncertain, never silently priced as zero.

Reservation assumes every counted input token is a cache write at the long-context
rate, plus the full output limit at the long-context output rate. Actual reported
usage releases unused money through the existing atomic SQLite settlement.
This deliberately conservative reservation may refuse a request whose eventual
cost would fit. Invalid usage, transport failure, unexpected processing tier or
usage beyond authorized bounds retains the entire reservation as uncertain.
This cannot undo an upstream billing or token-count contract violation.

Official sources:

- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/models/gpt-6-sol
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/token-counting
- https://developers.openai.com/api/reference/typescript/resources/responses

## Source and verification

Source was recovered from the repository's published Python wheel because the
repository did not contain unpacked source or tests. Original repository HEAD:
`87219a72814ee8eaeda435930685997071b8a608`. Original wheel Git blob:
`c131df48f8fa6a39c6870bb3eddb5d8a70deecfa` (verified before extraction).
Unmodified wallet ledger and command behavior were retained. A setuptools build
definition reproduces the published package name, entry point and dependency ranges.

From this candidate checkout, with development dependencies installed:

```text
python -m pytest -q
python -m build --wheel --no-isolation --outdir candidate_dist
```

The tests block network connections and use simulated providers plus a mocked
HTTP transport. They cover model-specific arithmetic, cache writes, long-context
boundaries, shared-wallet spending, rejection before generation, concurrent
reservation, lifecycle controls and conservative failure settlement.

Observed verification on Python 3.12, 17 October 2026: 57 source tests passed;
wheel build and local installation passed; installed CLI version and model
registry passed. The wheel's Python files matched the source byte for byte.
Candidate wheel SHA-256:
`05220644a9000cbadb95bf8224832900d2c3c6e65e9ca05d292ecfe74f3fff64`.
The published 0.2.0 wheel was preserved byte for byte. One dependency warning
concerns Starlette's future replacement of its httpx test client transport.

Before a public release: recheck pricing and model aliases, authorize tiny paid
live checks for each model using a dedicated low-limit key, compare the count
endpoint with returned usage and tier, test install/lifecycle on Windows, and
update published install/recruitment guidance only after the artifact is available.
Do not claim these checks have been performed based on offline tests.
