# MeterLock 0.3.0a3 — local alpha check

This check is for the visible local authority alpha. It does not require an API key or real money.

## Prerequisites

- Python 3.11+
- venv / pip
- a browser
- a trusted local computer

## Check the core story

1. Start the extracted alpha with `py -3 -I launch_meterlock.py` (or `python -I launch_meterlock.py`).
2. Confirm the first Attempt Lock shows limit 3, used 0, remaining 3.
3. Run the local action three times.
4. Confirm the counters show 3 / 3 / 0.
5. Try a fourth time.
6. Confirm MeterLock shows **STOP / ASK HUMAN** and the action is blocked.
7. Stop MeterLock and start it again.
8. Confirm the Attempt Lock remains exhausted.
9. Use the $1.00 sample Spend Lock for five $0.20 spends.
10. Confirm the sixth spend is refused with **STOP / ASK HUMAN**.
11. Restart again and confirm the exhausted spend state remains.
12. Check Recent activity for allowed and blocked entries.

## What this proves

It proves the visible local path can consume finite authority, refuse after exhaustion, and preserve the exhausted state across restart.

It does **not** prove production security, arbitrary-code containment, broad provider compatibility or a signed consumer installer.

## Reporting bugs

For a non-sensitive bug, open a GitHub issue with:

- operating system;
- Python version;
- exact step that failed;
- exact error text if available.

Do not post secrets, API keys, private prompts or sensitive data.
