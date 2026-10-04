# MeterLock external developer alpha v0.2.0

Status: **READY FOR INDEPENDENT TESTING — NOT YET EXTERNALLY VALIDATED**

Proven before this release:

- Stage A live: concurrent requests did not collectively authorise spend above the locked allowance.
- Stage B live: scoped key creation, real spend, restart persistence, pause/block, resume/spend, revoke/block, and revoked-state persistence all passed.

This release changes the delivery boundary, not the core money invariant: it packages the local gateway as an installable `meterlock` command so an external developer can test it without giving MeterLock hosted custody of their upstream OpenAI credential.

The next evidence required is an independent user successfully completing [ALPHA_TEST.md](ALPHA_TEST.md) without bespoke implementation work.