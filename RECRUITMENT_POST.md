# External-alpha recruitment copy

## Short version

Built a local OpenAI gateway that gives one AI agent/run a **finite wallet**.

Looking for 3–5 technical alpha testers.

- Windows / Python / OpenAI API preferred
- about 10–15 minutes
- **100% async — no calls, Zooms, meetings, or calendar booking**
- test: create a $0.01 wallet → spend → pause → resume → revoke
- early alpha: use a disposable low-limit provider key and no sensitive prompts

GitHub: https://github.com/P-N-8/meterlock

## Longer version

I built an early local developer alpha called **MeterLock**.

The idea is simple: instead of setting a monthly limit for an entire provider project, give one AI agent/run a finite wallet. MeterLock reserves budget before forwarding a supported generation request and refuses a request when the remaining wallet cannot authorise it.

I am looking for 3–5 independent technical testers who already use the OpenAI API.

Current alpha:
- local gateway
- OpenAI only
- Python 3.11+
- Windows is the most-tested path
- tiny test wallets only

The test should take roughly 10–15 minutes if installation goes smoothly.

**No calls or meetings. This is deliberately asynchronous.**

The task is:
1. install MeterLock;
2. create a $0.01 wallet;
3. send a request through it;
4. pause and confirm another request is blocked;
5. resume and confirm it can run;
6. revoke and confirm the scoped key is dead.

If installation fails, that is useful evidence too.

Please use a dedicated low-limit OpenAI project/key and no sensitive prompts.

https://github.com/P-N-8/meterlock
