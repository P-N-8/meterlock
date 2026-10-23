from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from . import __version__
from .config import NANODOLLARS_PER_DOLLAR
from .ledger import SQLiteLedger


def default_home() -> Path:
    return Path(os.environ.get("METERLOCK_HOME", Path.home() / ".meterlock"))


def default_db() -> Path:
    return Path(os.environ.get("METERLOCK_DB", default_home() / "meterlock.db"))


def _ledger() -> SQLiteLedger:
    path = default_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteLedger(path)


def _budget_nd(text: str) -> int:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise SystemExit("budget must be decimal text, e.g. 5 or 0.50") from exc
    if value <= 0:
        raise SystemExit("budget must be positive")
    return int((value * NANODOLLARS_PER_DOLLAR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _usd(nd: int) -> str:
    return f"${Decimal(nd) / Decimal(NANODOLLARS_PER_DOLLAR):.9f}".rstrip("0").rstrip(".")


def cmd_start(args: argparse.Namespace) -> int:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        key = getpass.getpass("OpenAI API key (hidden; held only in this process): ").strip()
    if not key:
        raise SystemExit("OpenAI API key is required")

    home = default_home()
    home.mkdir(parents=True, exist_ok=True)
    os.environ["OPENAI_API_KEY"] = key
    os.environ["METERLOCK_DB"] = str(default_db())
    # Admin HTTP endpoints remain closed to ordinary local-alpha use.
    os.environ.setdefault("METERLOCK_ADMIN_TOKEN", secrets.token_urlsafe(32))

    print("\nMeterLock external alpha starting")
    print(f"Gateway: http://{args.host}:{args.port}/v1")
    print(f"Ledger:  {default_db()}")
    print("Upstream OpenAI key is not written to MeterLock's database.")
    print("Create a lock in a second terminal with: meterlock create ...\n")

    import uvicorn
    # Import after environment is configured.
    from .api import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    if args.minutes < 1 or args.minutes > 10080:
        raise SystemExit("--minutes must be 1..10080")
    ledger = _ledger()
    lock_id, raw_key = ledger.create_lock(
        args.label,
        _budget_nd(args.budget),
        time.time() + args.minutes * 60,
    )
    state = ledger.state(lock_id)
    print("\nLOCK CREATED")
    print(f"Lock ID:    {lock_id}")
    print(f"Label:      {state.label}")
    print(f"Budget:     {_usd(state.budget_nd)}")
    print(f"Expires in: {args.minutes} minutes")
    print("\nScoped MeterLock key (shown once):")
    print(raw_key)
    print("\nUse with an OpenAI-compatible client:")
    print("Base URL: http://127.0.0.1:8787/v1")
    print("API key:  the mlk_live_... key above")
    return 0


def _print_state(state) -> None:
    print(
        f"{state.lock_id}  {state.status:<7}  "
        f"budget={_usd(state.budget_nd)}  spent={_usd(state.spent_nd)}  "
        f"reserved={_usd(state.reserved_nd)}  remaining={_usd(state.available_nd)}  "
        f"label={state.label}"
    )


def cmd_list(args: argparse.Namespace) -> int:
    states = _ledger().list_states()
    if not states:
        print("No MeterLocks yet.")
        return 0
    for state in states:
        _print_state(state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        _print_state(_ledger().state(args.lock_id))
    except KeyError:
        raise SystemExit("lock not found")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    try:
        ledger = _ledger(); ledger.set_paused(args.lock_id, True); _print_state(ledger.state(args.lock_id))
    except KeyError:
        raise SystemExit("lock not found")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    try:
        ledger = _ledger(); ledger.set_paused(args.lock_id, False); _print_state(ledger.state(args.lock_id))
    except KeyError:
        raise SystemExit("lock not found")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    try:
        ledger = _ledger(); ledger.revoke(args.lock_id); _print_state(ledger.state(args.lock_id))
    except KeyError:
        raise SystemExit("lock not found")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meterlock", description="MeterLock external developer alpha")
    parser.add_argument("--version", action="version", version=f"MeterLock external alpha {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start", help="start the local MeterLock gateway")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("create", help="create a finite wallet and scoped agent key")
    p.add_argument("--label", required=True)
    p.add_argument("--budget", required=True, help="USD amount, e.g. 5 or 0.25")
    p.add_argument("--minutes", type=int, default=60)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list", help="list locks")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("status", help="show one lock")
    p.add_argument("lock_id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("pause", help="pause a lock")
    p.add_argument("lock_id")
    p.set_defaults(func=cmd_pause)

    p = sub.add_parser("resume", help="resume a lock")
    p.add_argument("lock_id")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("revoke", help="permanently revoke a lock")
    p.add_argument("lock_id")
    p.set_defaults(func=cmd_revoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
