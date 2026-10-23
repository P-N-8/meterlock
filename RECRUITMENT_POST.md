# MeterLock 0.3.0a3 — prospective early-access outreach

**Status:** draft outreach copy only. The 0.3.0a3 candidate is verified locally but is not yet published as a downloadable GitHub Release. Do not promise an available installer or live provider integration.

## Short version

**Your AI cannot exceed the authority you gave it.**

MeterLock is a local developer alpha for finite external authority. Give a named action three attempts; the fourth is stopped before reaching its local target. Or try a $1 simulated spend wallet; the sixth $0.20 spend is refused. Exhaustion survives restart, and Recent Activity shows what was allowed or blocked.

We're preparing a downloadable 0.3.0a3 alpha and looking for early users building AI agents who need actual external limits, not instructions in a prompt. No API key, real money, meeting or call is required for the visible demo.

GitHub: https://github.com/P-N-8/meterlock

## Longer version

MeterLock sits outside an AI model and enforces the finite authority that a trusted owner configured, **for actions routed through MeterLock**.

The currently verified local browser alpha demonstrates:
- Attempt Lock: three permitted local HTTP actions, fourth refused before dispatch;
- Spend Lock: a simulated $1 finite wallet, with five $0.20 spends allowed and sixth refused;
- STOP / ASK HUMAN on exhaustion;
- persistence across restart and a Recent Activity view.

The visible demo requires Python 3.11+, a browser and a trusted local machine. It uses no provider credentials, paid API call, account or cloud backend. The current version is a release candidate, not a public downloadable release yet.

We are especially interested in hearing where an external finite-authority check would fit in real agent workflows and what makes installation difficult. Async messages only; no calls or meetings.

This is experimental developer-alpha software, not a sandbox for hostile code or a production-security boundary. The current real-provider gateway is separate experimental functionality and has not been qualified by the visible demo.

GitHub: https://github.com/P-N-8/meterlock
