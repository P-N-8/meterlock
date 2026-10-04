# MeterLock external alpha test

We are looking for a small number of independent technical testers.

Please do not evaluate the idea in the abstract. Try the workflow.

## The task

1. Install MeterLock from the README.
2. Start the local gateway with a **dedicated low-limit OpenAI key**.
3. Create a **$0.01** wallet that expires in 30 minutes.
4. Send at least one supported request through the MeterLock base URL using the returned `mlk_live_...` key.
5. Run `meterlock status LOCK_ID`.
6. Pause the lock and confirm another request is blocked.
7. Resume it and confirm a request can run again.
8. Revoke it and confirm the scoped key cannot spend again.

Do not use production credentials, sensitive prompts, valuable workloads, or a provider project without its own small hard limit.

## Supported request

The current alpha accepts only:

- `POST /v1/responses`
- model `gpt-5.6-luna`
- non-empty plain-text `input`
- explicit `max_output_tokens` from 16 to 500

## What we want to learn

Open one GitHub issue titled `Alpha feedback: <short description>` and tell us:

- operating system;
- Python version;
- whether installation worked without bespoke help;
- whether the finite-wallet idea was immediately understandable;
- where you got stuck;
- whether pause/resume/revoke behaved as expected;
- whether you would use this for an unattended agent/run;
- whether you would pay for a polished self-service version, and roughly what problem it would need to protect.

Please do **not** include API keys, scoped MeterLock keys, prompts containing private data, or other secrets in issues or screenshots.

A failed install is useful evidence. Tell us the exact step and error instead of fighting it for an hour.