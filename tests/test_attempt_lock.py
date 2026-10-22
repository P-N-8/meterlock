from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from meterlock.attempt_lock import AttemptLock, AuthorityAlreadyExists


SRC = Path(__file__).resolve().parents[1] / "src"
DEMO = Path(__file__).resolve().parents[1] / "tools" / "attempt_lock_demo.py"


def test_three_actions_then_stop_before_execution(tmp_path):
    path = tmp_path / "attempts.db"
    lock = AttemptLock(path)
    lock.create("task", "action", 3)
    effects = []
    def effect():
        # A different connection observes the committed reservation at dispatch.
        effects.append(AttemptLock(path).state("task", "action")["used"])
    decisions = [lock.run("task", "action", effect) for _ in range(4)]
    assert effects == [1, 2, 3]
    assert [d["attempt_number"] for d in decisions] == [1, 2, 3, None]
    assert [d["outcome"] for d in decisions] == ["ALLOW"] * 3 + ["STOP"]
    assert decisions[-1]["next_step"] == "ASK_HUMAN"
    assert decisions[-1]["reason"] == "ATTEMPT_LIMIT_EXHAUSTED"
    assert decisions[-1]["executed"] is False
    assert decisions[-1]["state"]["remaining"] == 0
    assert decisions[-1]["state"]["exhausted"] is True
    json.dumps(decisions)


def test_reopen_preserves_exhaustion_and_recreate_cannot_reset(tmp_path):
    path = tmp_path / "attempts.db"
    first = AttemptLock(path)
    first.create("task", "action", 1)
    first.run("task", "action", lambda: "executed")
    before = first.state("task", "action")
    del first
    reopened = AttemptLock(path)
    with pytest.raises(AuthorityAlreadyExists):
        reopened.create("task", "action", 999)
    assert reopened.state("task", "action") == before
    decision = reopened.run("task", "action", lambda: pytest.fail("Refused action executed"))
    assert (decision["outcome"], decision["next_step"], decision["executed"]) == ("STOP", "ASK_HUMAN", False)


def test_missing_authority_does_not_implicitly_create_permission(tmp_path):
    lock = AttemptLock(tmp_path / "attempts.db")
    result = lock.run("unknown", "action", lambda: pytest.fail("Unknown action executed"))
    assert result["reason"] == "AUTHORITY_NOT_FOUND"
    assert result["outcome"] == "STOP" and result["next_step"] == "ASK_HUMAN"
    assert not result["executed"]


def test_task_action_scopes_are_independent_and_exact(tmp_path):
    lock = AttemptLock(tmp_path / "attempts.db")
    lock.create("task", "action-a", 1)
    lock.create("task", "action-b", 2)
    lock.create("other-task", "action-a", 3)
    lock.run("task", "action-a", lambda: None)
    assert lock.state("task", "action-b")["remaining"] == 2
    assert lock.state("other-task", "action-a")["remaining"] == 3
    assert lock.run("task", "Action-a", lambda: pytest.fail("Wrong action executed"))["outcome"] == "STOP"


def test_zero_limit_is_immediately_exhausted(tmp_path):
    lock = AttemptLock(tmp_path / "attempts.db")
    assert lock.create("task", "action", 0)["exhausted"]
    assert lock.run("task", "action", lambda: pytest.fail("Zero-limit action executed"))["outcome"] == "STOP"


@pytest.mark.parametrize("limit", [-1, True, False, 1.5, "3", None, 2**63])
def test_invalid_limits_are_refused(tmp_path, limit):
    lock = AttemptLock(tmp_path / "attempts.db")
    with pytest.raises(ValueError):
        lock.create("task", "action", limit)


@pytest.mark.parametrize("task,action", [("", "a"), (" ", "a"), (None, "a"),
                                         ("t", ""), ("t", " "), ("t", None)])
def test_invalid_identities_are_refused(tmp_path, task, action):
    lock = AttemptLock(tmp_path / "attempts.db")
    with pytest.raises(ValueError):
        lock.create(task, action, 3)
    with pytest.raises(ValueError):
        lock.reserve(task, action)


@pytest.mark.parametrize("path", ["", " ", ":memory:", "file:memory?mode=memory"])
def test_nonpersistent_databases_are_refused(path):
    with pytest.raises(ValueError):
        AttemptLock(path)


def test_failed_action_keeps_attempt_consumed(tmp_path):
    lock = AttemptLock(tmp_path / "attempts.db")
    lock.create("task", "action", 1)
    def failed_action():
        raise RuntimeError("simulated failure")
    with pytest.raises(RuntimeError, match="simulated failure"):
        lock.run("task", "action", failed_action)
    assert lock.state("task", "action")["used"] == 1
    assert lock.run("task", "action", lambda: pytest.fail("Refund allowed retry"))["outcome"] == "STOP"


def test_noncallable_does_not_consume_permission(tmp_path):
    lock = AttemptLock(tmp_path / "attempts.db")
    lock.create("task", "action", 1)
    with pytest.raises(TypeError):
        lock.run("task", "action", None)
    assert lock.state("task", "action")["used"] == 0


def test_reentrant_action_cannot_bypass_limit(tmp_path):
    lock = AttemptLock(tmp_path / "attempts.db")
    lock.create("task", "action", 1)
    outer = lock.run("task", "action", lambda: lock.run(
        "task", "action", lambda: pytest.fail("Reentrant action bypassed limit")))
    assert outer["executed"] and outer["result"]["outcome"] == "STOP"
    assert not outer["result"]["executed"]


def test_database_update_failure_stops_before_action_and_rolls_back(tmp_path):
    path = tmp_path / "attempts.db"
    lock = AttemptLock(path)
    lock.create("task", "action", 3)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TRIGGER refuse_update BEFORE UPDATE ON attempt_locks "
                     "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        conn.commit()
    decision = lock.run("task", "action", lambda: pytest.fail("Uncommitted action executed"))
    assert decision["reason"] == "AUTHORITY_STATE_UNAVAILABLE"
    assert decision["outcome"] == "STOP" and not decision["executed"]
    assert lock.state("task", "action")["used"] == 0


def test_missing_database_table_fails_closed(tmp_path):
    path = tmp_path / "attempts.db"
    lock = AttemptLock(path)
    lock.create("task", "action", 3)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DROP TABLE attempt_locks")
        conn.commit()
    result = lock.run("task", "action", lambda: pytest.fail("Broken state allowed action"))
    assert result["outcome"] == "STOP" and result["next_step"] == "ASK_HUMAN"
    assert result["reason"] == "AUTHORITY_STATE_UNAVAILABLE"


def test_concurrent_threads_get_only_three_grants(tmp_path):
    path = tmp_path / "attempts.db"
    AttemptLock(path).create("task", "action", 3)
    with ThreadPoolExecutor(max_workers=12) as pool:
        decisions = list(pool.map(lambda _: AttemptLock(path).run("task", "action", lambda: "effect"), range(12)))
    assert sum(d["executed"] for d in decisions) == 3
    assert sorted(d["attempt_number"] for d in decisions if d["executed"]) == [1, 2, 3]
    assert AttemptLock(path).state("task", "action")["used"] == 3


CHILD_PREFIX = """import sys, json, os
def guard(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('Network forbidden in Attempt Lock test')
sys.addaudithook(guard)
sys.path.insert(0, sys.argv[1])
from meterlock.attempt_lock import AttemptLock
lock=AttemptLock(sys.argv[2])
"""


def test_abrupt_process_exit_after_reservation_never_refunds(tmp_path):
    path = tmp_path / "attempts.db"
    lock = AttemptLock(path)
    lock.create("task", "action", 1)
    code = CHILD_PREFIX + "\nlock.reserve('task','action')\nos._exit(0)\n"
    subprocess.run([sys.executable, "-I", "-c", code, str(SRC), str(path)],
                   check=True, timeout=15, capture_output=True, text=True)
    decision = AttemptLock(path).run("task", "action", lambda: pytest.fail("Restart refunded reservation"))
    assert decision["reason"] == "ATTEMPT_LIMIT_EXHAUSTED"
    assert decision["state"]["used"] == 1


def test_independent_concurrent_processes_share_only_three_attempts(tmp_path):
    path = tmp_path / "attempts.db"
    AttemptLock(path).create("task", "action", 3)
    code = CHILD_PREFIX + "\nprint(json.dumps(lock.run('task','action',lambda: 'effect')))\n"
    processes = [subprocess.Popen([sys.executable, "-I", "-c", code, str(SRC), str(path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(8)]
    decisions = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            decisions.append(json.loads(stdout))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert sum(d["executed"] for d in decisions) == 3
    assert sorted(d["attempt_number"] for d in decisions if d["executed"]) == [1, 2, 3]
    assert sum(d["outcome"] == "STOP" for d in decisions) == 5
    assert AttemptLock(path).state("task", "action")["exhausted"] is True


def test_demo_proves_execution_cutoff_and_fresh_process_restart():
    child = subprocess.run([sys.executable, "-I", str(DEMO)], capture_output=True,
                           text=True, timeout=30, check=True)
    result = json.loads(child.stdout)
    assert result["status"] == "PASS"
    assert [e["attempt"] for e in result["simulated_effects"]] == [1, 2, 3]
    assert result["process_runs"][1]["recreate_after_restart"] == "REFUSED"
    assert result["process_runs"][1]["decisions"][0]["executed"] is False
