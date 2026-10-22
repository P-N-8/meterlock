"""Attempt Lock v0.1: persistent, consumable authority for one task/action.

Standard library only. A committed reservation consumes one attempt permanently;
failed actions and crashes do not refund it. Callers must retain the same trusted
database and task/action identities. This is not a sandbox against its owner.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any, Callable


class AuthorityAlreadyExists(ValueError):
    """Creating the same task/action again must never reset its counter."""


class AttemptLock:
    def __init__(self, db_path: str | Path):
        raw_path = str(db_path)
        if not raw_path.strip() or raw_path == ":memory:" or raw_path.startswith("file:"):
            raise ValueError("Attempt Lock requires a persistent filesystem database")
        self.db_path = str(Path(raw_path).resolve())
        with closing(self._connect()) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS attempt_locks (
                task_id TEXT NOT NULL,
                action TEXT NOT NULL,
                max_attempts INTEGER NOT NULL
                    CHECK (typeof(max_attempts) = 'integer' AND max_attempts >= 0),
                used INTEGER NOT NULL DEFAULT 0
                    CHECK (typeof(used) = 'integer' AND used >= 0 AND used <= max_attempts),
                PRIMARY KEY (task_id, action)
            )""")

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @staticmethod
    def _identity(task_id, action):
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action must be a non-empty string")

    @staticmethod
    def _state(row):
        return {
            "task_id": row["task_id"], "action": row["action"],
            "max_attempts": row["max_attempts"], "used": row["used"],
            "remaining": row["max_attempts"] - row["used"],
            "exhausted": row["used"] == row["max_attempts"],
        }

    def create(self, task_id: str, action: str, max_attempts: int) -> dict[str, Any]:
        self._identity(task_id, action)
        if type(max_attempts) is not int or not 0 <= max_attempts <= 2**63 - 1:
            raise ValueError("max_attempts must be a non-negative SQLite integer")
        with closing(self._connect()) as conn:
            try:
                conn.execute("INSERT INTO attempt_locks(task_id, action, max_attempts) VALUES(?,?,?)",
                             (task_id, action, max_attempts))
            except sqlite3.IntegrityError as exc:
                raise AuthorityAlreadyExists("Task/action authority already exists; no reset allowed") from exc
        return self.state(task_id, action)

    def state(self, task_id: str, action: str) -> dict[str, Any]:
        self._identity(task_id, action)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM attempt_locks WHERE task_id=? AND action=?",
                               (task_id, action)).fetchone()
        if row is None:
            raise KeyError((task_id, action))
        return self._state(row)

    @staticmethod
    def _stop(task_id, action, reason, state=None):
        return {
            "outcome": "STOP", "next_step": "ASK_HUMAN", "reason": reason,
            "task_id": task_id, "action": action, "attempt_number": None,
            "state": state,
        }

    def reserve(self, task_id: str, action: str) -> dict[str, Any]:
        """Commit one non-refundable attempt before returning ALLOW.

        BEGIN IMMEDIATE serializes independent connections/processes. No callback
        runs while the transaction is open, and no completion/refund can reset it.
        """
        self._identity(task_id, action)
        try:
            with closing(self._connect()) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute("SELECT * FROM attempt_locks WHERE task_id=? AND action=?",
                                       (task_id, action)).fetchone()
                    if row is None:
                        result = self._stop(task_id, action, "AUTHORITY_NOT_FOUND")
                    elif row["used"] >= row["max_attempts"]:
                        result = self._stop(task_id, action, "ATTEMPT_LIMIT_EXHAUSTED", self._state(row))
                    else:
                        conn.execute("UPDATE attempt_locks SET used=used+1 WHERE task_id=? AND action=?",
                                     (task_id, action))
                        state = self._state(row)
                        state.update(used=row["used"] + 1,
                                     remaining=row["max_attempts"] - row["used"] - 1,
                                     exhausted=row["used"] + 1 == row["max_attempts"])
                        result = {
                            "outcome": "ALLOW", "next_step": "EXECUTE",
                            "reason": "ATTEMPT_RESERVED", "task_id": task_id,
                            "action": action, "attempt_number": state["used"], "state": state,
                        }
                    conn.execute("COMMIT")
                    return result
                except Exception:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
        except sqlite3.Error:
            return self._stop(task_id, action, "AUTHORITY_STATE_UNAVAILABLE")

    def run(self, task_id: str, action: str, callback: Callable[[], Any]) -> dict[str, Any]:
        """Invoke a caller-supplied action only after a durable reservation.

        A callback exception propagates, with the attempt remaining consumed.
        The returned decision is evidence, not a reusable execution credential.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        decision = self.reserve(task_id, action)
        if decision["outcome"] != "ALLOW":
            return {**decision, "executed": False, "result": None}
        result = callback()
        return {**decision, "executed": True, "result": result}
