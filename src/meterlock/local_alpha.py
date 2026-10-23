"""Tiny local browser alpha; existing enforcement, local effects, no API key.

UI history is evidence, never authority. SQLite Attempt Lock and wallet state
remain authoritative even if an action is interrupted before history completes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from pathlib import Path
import secrets
import socketserver
import sqlite3
import threading
import time
import webbrowser

from . import __version__
from .attempt_http import AttemptHTTPAction
from .attempt_lock import AttemptLock, AuthorityAlreadyExists
from .ledger import InsufficientAllowance, LockUnavailable, SQLiteLedger

ACTION = "local-http-action"


class AlphaState:
    def __init__(self, directory: Path):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "alpha.db"
        self.wallet = SQLiteLedger(self.path)
        self.attempts = AttemptLock(self.path)
        self.operations = threading.Lock()
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS alpha_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alpha_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                    task TEXT NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL,
                    message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alpha_receipts (
                    event_id INTEGER PRIMARY KEY, task TEXT NOT NULL, committed_used INTEGER NOT NULL);
            """)
        try:
            self.attempts.create("First task", ACTION, 3)
        except AuthorityAlreadyExists:
            pass
        if self.meta("selected") is None:
            self.set_meta("selected", "First task")
        if self.meta("wallet") is None:
            # INSERT OR IGNORE retains one canonical sample wallet if two UIs
            # initialize together. An unused concurrent wallet is never selected.
            wallet_id, _ = self.wallet.create_lock("Sample Spend Lock", 1_000_000_000,
                                                  time.time() + 365 * 86400)
            with closing(self.connect()) as db:
                db.execute("INSERT OR IGNORE INTO alpha_meta VALUES('wallet',?)", (wallet_id,))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def meta(self, name):
        with closing(self.connect()) as db:
            row = db.execute("SELECT value FROM alpha_meta WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def set_meta(self, name, value):
        with closing(self.connect()) as db:
            db.execute("INSERT INTO alpha_meta VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                       (name, value))

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 for c in value):
            raise ValueError("Give the task a name between 1 and 80 characters.")
        return value.strip()

    def event(self, task, kind):
        with closing(self.connect()) as db:
            return db.execute("INSERT INTO alpha_activity(at,task,kind,outcome,message) VALUES(?,?,?,'pending',?)",
                              (datetime.now(timezone.utc).isoformat(), task, kind,
                               "Outcome unconfirmed. The saved counter is authoritative.")).lastrowid

    def finish(self, event, outcome, message):
        with closing(self.connect()) as db:
            db.execute("UPDATE alpha_activity SET outcome=?,message=? WHERE id=?", (outcome, message, event))

    def create(self, task, limit):
        task = self.name(task)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Choose a limit from 1 to 100 attempts.")
        self.attempts.create(task, ACTION, limit)
        self.set_meta("selected", task)
        event = self.event(task, "create")
        self.finish(event, "created", f"Created a separate limit of {limit} attempts.")

    def select(self, task):
        task = self.name(task)
        self.attempts.state(task, ACTION)
        self.set_meta("selected", task)

    def run_action(self, task, target_url, marker):
        task = self.name(task)
        event = self.event(task, "attempt")
        # Only this adapter can dispatch the action. No URL comes from the UI.
        result = AttemptHTTPAction(self.attempts, task, ACTION, target_url).send(
            json.dumps({"marker": marker, "task": task, "event": event}).encode())
        if result["outcome"] == "STOP":
            outcome, message = "blocked", "STOP / ASK HUMAN. Blocked before reaching the local action."
        elif result["http"]["outcome"] == "SUCCESS":
            outcome, message = "allowed", "Local action completed. One attempt used."
        else:
            outcome, message = "failed", "Local action failed. Its reserved attempt remains used."
        self.finish(event, outcome, message)
        return {"outcome": result["outcome"], "next_step": result["next_step"],
                "reason": result["reason"], "result": outcome, "message": message,
                "dispatch_attempted": result["dispatch_attempted"]}

    def sample_spend(self):
        event = self.event("Sample wallet", "spend")
        try:
            # Local demonstration values, no model pricing or paid provider.
            reservation = self.wallet.reserve(self.meta("wallet"), 200_000_000)
            self.wallet.settle(reservation, 200_000_000)
        except (InsufficientAllowance, LockUnavailable):
            outcome, message = "blocked", "STOP / ASK HUMAN. Sample Spend Lock refused this spend."
        else:
            outcome, message = "allowed", "Sample $0.20 spend completed. No real money moved."
        self.finish(event, outcome, message)
        return {"outcome": "STOP" if outcome == "blocked" else "ALLOW",
                "next_step": "ASK_HUMAN" if outcome == "blocked" else "EXECUTE",
                "result": outcome, "message": message}

    def snapshot(self):
        with closing(self.connect()) as db:
            tasks = [r[0] for r in db.execute("SELECT task_id FROM attempt_locks WHERE action=? ORDER BY rowid", (ACTION,))]
            history = [dict(r) for r in db.execute("SELECT * FROM alpha_activity ORDER BY id DESC LIMIT 40")]
            receipts = [dict(r) for r in db.execute("SELECT * FROM alpha_receipts ORDER BY event_id")]
        wallet = self.wallet.state(self.meta("wallet"))
        return {"selected": self.meta("selected"),
                "authorities": [self.attempts.state(t, ACTION) for t in tasks],
                "wallet": {"budget": f"${wallet.budget_nd / 1e9:.2f}",
                           "spent": f"${wallet.spent_nd / 1e9:.2f}",
                           "remaining": f"${wallet.available_nd / 1e9:.2f}",
                           "held": f"${wallet.reserved_nd / 1e9:.2f}", "status": wallet.status},
                "history": history, "local_actions_completed": len(receipts)}


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # Loopback literal only; skip HTTPServer's optional reverse DNS lookup.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload, content_type="application/json"):
        body = json.dumps(payload).encode() if content_type == "application/json" else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; "
                         f"script-src 'nonce-{self.server.ui_token}'; connect-src 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        return self.client_address[0] == "127.0.0.1" and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 4096 or self.headers.get("Transfer-Encoding"):
            raise ValueError("Request is too large or incomplete.")
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise ValueError("Expected a small action request.")
        return value


class TargetHandler(Handler):
    def do_POST(self):
        self.server.received += 1
        try:
            value = self.read_json()
            if (not self.local_host() or self.path != "/local-action"
                    or not isinstance(value.get("marker"), str)
                    or not secrets.compare_digest(value["marker"].encode(), self.server.marker.encode())):
                return self.reply(403, {"error": "Local adapter only."})
            state = self.server.state
            task = state.name(value.get("task"))
            with closing(state.connect()) as db:
                pending = db.execute("SELECT task,kind,outcome FROM alpha_activity WHERE id=?", (value.get("event"),)).fetchone()
                if pending is None or tuple(pending) != (task, "attempt", "pending"):
                    return self.reply(403, {"error": "No matching action intent."})
                used = state.attempts.state(task, ACTION)["used"]
                if used < 1:
                    return self.reply(403, {"error": "No reserved attempt."})
                db.execute("INSERT INTO alpha_receipts VALUES(?,?,?)", (value["event"], task, used))
            self.reply(200, {"completed": True})
        except (ValueError, KeyError, sqlite3.Error):
            self.reply(400, {"error": "Local action was not completed."})


class UIHandler(Handler):
    def do_GET(self):
        if not self.local_host():
            return self.reply(403, {"error": "Open MeterLock using its local address."})
        if self.path == "/":
            html = files("meterlock").joinpath("local_alpha.html").read_text(encoding="utf-8")
            html = html.replace("__UI_TOKEN__", self.server.ui_token).replace("__VERSION__", __version__)
            return self.reply(200, html.encode(), "text/html")
        if self.path == "/api/state":
            with self.server.state.operations:
                return self.reply(200, self.server.state.snapshot())
        if self.path == "/favicon.ico":
            return self.reply(204, b"", "image/x-icon")
        self.reply(404, {"error": "Page not found."})

    def do_POST(self):
        if (not self.local_host() or self.headers.get("Origin") != self.server.origin
                or not secrets.compare_digest(self.headers.get("X-MeterLock-UI", "").encode(), self.server.ui_token.encode())
                or self.headers.get_content_type() != "application/json"):
            return self.reply(403, {"error": "Use the controls in the MeterLock window."})
        try:
            value = self.read_json()
            state = self.server.state
            with state.operations:
                result = None
                if self.path == "/api/create":
                    state.create(value.get("task"), value.get("limit"))
                elif self.path == "/api/select":
                    state.select(value.get("task"))
                elif self.path == "/api/action":
                    result = state.run_action(value.get("task"), self.server.target_url, self.server.marker)
                elif self.path == "/api/spend":
                    result = state.sample_spend()
                else:
                    return self.reply(404, {"error": "Action not found."})
                self.reply(200, {"state": state.snapshot(), "decision": result})
        except AuthorityAlreadyExists:
            self.reply(409, {"error": "That task already exists. Select it to keep its saved limit."})
        except (ValueError, KeyError):
            self.reply(400, {"error": "Choose a saved task, or a new name and a limit from 1 to 100."})
        except (sqlite3.Error, OSError):
            self.reply(503, {"error": "MeterLock could not finish safely. Refresh saved state before trying again."})


class VisibleAlpha:
    def __init__(self, directory: Path, port=0):
        self.state = AlphaState(directory)
        marker, token = secrets.token_hex(32), secrets.token_hex(32)
        self.target = LocalServer(("127.0.0.1", 0), TargetHandler)
        self.target.state, self.target.marker, self.target.ui_token, self.target.received = self.state, marker, token, 0
        try:
            self.ui = LocalServer(("127.0.0.1", port), UIHandler)
        except Exception:
            self.target.server_close()
            raise
        self.url = f"http://127.0.0.1:{self.ui.server_port}"
        self.ui.origin, self.ui.ui_token, self.ui.marker, self.ui.state = self.url, token, marker, self.state
        self.ui.target_url = f"http://127.0.0.1:{self.target.server_port}/local-action"
        self.threads = []

    def start(self):
        for server in (self.target, self.ui):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        for server in (self.ui, self.target):
            if self.threads:
                server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="MeterLock tiny local browser alpha")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".meterlock" / "visible-alpha")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    app = VisibleAlpha(args.data_dir, args.port)
    app.start()
    print(f"MeterLock {__version__} is ready: {app.url}", flush=True)
    print("Keep this window open. Ctrl+C stops MeterLock; your limits stay saved.", flush=True)
    try:
        if not args.no_browser:
            try:
                webbrowser.open(app.url)
            except (webbrowser.Error, OSError):
                print("Open the local address above in your browser.", flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()


if __name__ == "__main__":
    main()
