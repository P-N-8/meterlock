from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


class InsufficientAllowance(Exception):
    def __init__(self, remaining_nd: int, requested_nd: int):
        self.remaining_nd = remaining_nd
        self.requested_nd = requested_nd
        super().__init__(f"remaining={remaining_nd} requested={requested_nd}")


class LockUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LockState:
    lock_id: str
    label: str
    budget_nd: int
    spent_nd: int
    reserved_nd: int
    expires_at: float
    paused: bool
    revoked: bool

    @property
    def available_nd(self) -> int:
        return max(0, self.budget_nd - self.spent_nd - self.reserved_nd)

    @property
    def status(self) -> str:
        now = time.time()
        if self.revoked:
            return "revoked"
        if self.paused:
            return "paused"
        if self.expires_at <= now:
            return "expired"
        if self.available_nd <= 0:
            return "exhausted"
        return "active"


class SQLiteLedger:
    """Persistent alpha ledger with Stage-A atomic reserve semantics.

    Every authorization predicate and reservation insert occurs inside one
    BEGIN IMMEDIATE transaction. A scoped MeterLock key is stored only as a
    SHA-256 digest; the plaintext key is returned once at creation time.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS locks (
                    lock_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    budget_nd INTEGER NOT NULL CHECK (budget_nd >= 0),
                    spent_nd INTEGER NOT NULL DEFAULT 0 CHECK (spent_nd >= 0),
                    reserved_nd INTEGER NOT NULL DEFAULT 0 CHECK (reserved_nd >= 0),
                    expires_at REAL NOT NULL,
                    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0,1)),
                    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0,1)),
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    lock_id TEXT NOT NULL,
                    reserved_nd INTEGER NOT NULL CHECK (reserved_nd > 0),
                    state TEXT NOT NULL CHECK (state IN ('reserved','settled','uncertain')),
                    actual_nd INTEGER,
                    created_at REAL NOT NULL,
                    settled_at REAL,
                    FOREIGN KEY(lock_id) REFERENCES locks(lock_id)
                );
                CREATE INDEX IF NOT EXISTS idx_reservations_lock_id
                    ON reservations(lock_id);
                """
            )

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def create_lock(self, label: str, budget_nd: int, expires_at: float) -> tuple[str, str]:
        if not label.strip():
            raise ValueError("label cannot be empty")
        if budget_nd <= 0:
            raise ValueError("budget must be positive")
        if expires_at <= time.time():
            raise ValueError("expiry must be in the future")

        lock_id = "mlk_" + uuid.uuid4().hex
        raw_key = "mlk_live_" + secrets.token_urlsafe(32)
        key_hash = self._hash_key(raw_key)
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO locks
                   (lock_id,label,key_hash,budget_nd,spent_nd,reserved_nd,expires_at,paused,revoked,created_at)
                   VALUES(?,?,?,?,0,0,?,0,0,?)""",
                (lock_id, label.strip(), key_hash, budget_nd, expires_at, time.time()),
            )
        return lock_id, raw_key

    def _row_to_state(self, row: sqlite3.Row) -> LockState:
        return LockState(
            lock_id=row["lock_id"],
            label=row["label"],
            budget_nd=row["budget_nd"],
            spent_nd=row["spent_nd"],
            reserved_nd=row["reserved_nd"],
            expires_at=row["expires_at"],
            paused=bool(row["paused"]),
            revoked=bool(row["revoked"]),
        )

    def state(self, lock_id: str) -> LockState:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM locks WHERE lock_id=?", (lock_id,)).fetchone()
        if row is None:
            raise KeyError(lock_id)
        return self._row_to_state(row)

    def list_states(self) -> list[LockState]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM locks ORDER BY created_at DESC").fetchall()
        return [self._row_to_state(r) for r in rows]

    def authenticate_key(self, raw_key: str) -> LockState:
        if not raw_key:
            raise LockUnavailable("invalid_key", "MeterLock key is missing")
        digest = self._hash_key(raw_key)
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM locks").fetchall()
        # Do not make correctness depend on timing of a direct string equality.
        for row in rows:
            if hmac.compare_digest(row["key_hash"], digest):
                return self._row_to_state(row)
        raise LockUnavailable("invalid_key", "MeterLock key is invalid")

    def set_paused(self, lock_id: str, paused: bool) -> None:
        with closing(self._connect()) as conn:
            cur = conn.execute("UPDATE locks SET paused=? WHERE lock_id=?", (int(paused), lock_id))
        if cur.rowcount != 1:
            raise KeyError(lock_id)

    def revoke(self, lock_id: str) -> None:
        with closing(self._connect()) as conn:
            cur = conn.execute("UPDATE locks SET revoked=1 WHERE lock_id=?", (lock_id,))
        if cur.rowcount != 1:
            raise KeyError(lock_id)

    def reserve(self, lock_id: str, amount_nd: int) -> str:
        if amount_nd <= 0:
            raise ValueError("reservation must be positive")
        reservation_id = uuid.uuid4().hex
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM locks WHERE lock_id=?", (lock_id,)).fetchone()
                if row is None:
                    raise KeyError(lock_id)
                state = self._row_to_state(row)
                if state.revoked:
                    raise LockUnavailable("lock_revoked", "MeterLock has been revoked")
                if state.paused:
                    raise LockUnavailable("lock_paused", "MeterLock is paused")
                if state.expires_at <= time.time():
                    raise LockUnavailable("lock_expired", "MeterLock has expired")
                remaining = state.budget_nd - state.spent_nd - state.reserved_nd
                if amount_nd > remaining:
                    raise InsufficientAllowance(remaining, amount_nd)
                conn.execute(
                    "UPDATE locks SET reserved_nd = reserved_nd + ? WHERE lock_id=?",
                    (amount_nd, lock_id),
                )
                conn.execute(
                    """INSERT INTO reservations
                       (reservation_id, lock_id, reserved_nd, state, created_at)
                       VALUES (?, ?, ?, 'reserved', ?)""",
                    (reservation_id, lock_id, amount_nd, time.time()),
                )
                conn.execute("COMMIT")
                return reservation_id
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def settle(self, reservation_id: str, actual_nd: int) -> None:
        if actual_nd < 0:
            raise ValueError("actual cost cannot be negative")
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT lock_id, reserved_nd, state FROM reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(reservation_id)
                if row["state"] != "reserved":
                    raise ValueError("reservation is not open")
                if actual_nd > row["reserved_nd"]:
                    raise RuntimeError(
                        "SAFETY INVARIANT BROKEN: actual cost exceeded pre-authorized reservation"
                    )
                conn.execute(
                    """UPDATE locks
                       SET reserved_nd = reserved_nd - ?, spent_nd = spent_nd + ?
                       WHERE lock_id=?""",
                    (row["reserved_nd"], actual_nd, row["lock_id"]),
                )
                conn.execute(
                    """UPDATE reservations
                       SET state='settled', actual_nd=?, settled_at=?
                       WHERE reservation_id=?""",
                    (actual_nd, time.time(), reservation_id),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def mark_uncertain_full_cost(self, reservation_id: str) -> None:
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT lock_id, reserved_nd, state FROM reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(reservation_id)
                if row["state"] != "reserved":
                    raise ValueError("reservation is not open")
                conn.execute(
                    """UPDATE locks
                       SET reserved_nd = reserved_nd - ?, spent_nd = spent_nd + ?
                       WHERE lock_id=?""",
                    (row["reserved_nd"], row["reserved_nd"], row["lock_id"]),
                )
                conn.execute(
                    """UPDATE reservations
                       SET state='uncertain', actual_nd=?, settled_at=?
                       WHERE reservation_id=?""",
                    (row["reserved_nd"], time.time(), reservation_id),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
