import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import http.client
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from meterlock.attempt_http import AttemptHTTPAction
from meterlock.attempt_lock import AttemptLock, AuthorityAlreadyExists


@pytest.fixture
def transport(monkeypatch):
    """No sockets: constructor/request hooks independently inspect durable state."""
    class Transport:
        connections = []
        requests = []
        closed = []
        status = 200
        payload = b"ok"
        fault_at = None
        on_connect = staticmethod(lambda: None)

        def __init__(self, host, port, timeout):
            self.on_connect()
            self.connections.append((host, port, timeout))
            if self.fault_at == "constructor":
                raise OSError("simulated connect setup failure")

        def request(self, method, target, body, headers):
            self.on_connect()
            self.requests.append((method, target, body, headers))
            if self.fault_at == "request":
                raise ConnectionRefusedError("simulated refusal")

        def getresponse(self):
            if self.fault_at == "response":
                raise http.client.RemoteDisconnected("simulated disconnect")
            return self

        def read(self, size):
            assert size == 65537
            if self.fault_at == "read":
                raise TimeoutError("simulated timeout")
            return self.payload[:size]

        def close(self):
            self.closed.append(self)

    monkeypatch.setattr("meterlock.attempt_http.http.client.HTTPConnection", Transport)
    return Transport


@pytest.fixture
def bound(tmp_path):
    lock = AttemptLock(tmp_path / "authority.db")
    lock.create("task", "post-action", 3)
    return lock, AttemptHTTPAction(lock, "task", "post-action", "http://example.invalid:8080/action?q=1")


def test_committed_reservation_precedes_even_transport_construction(bound, transport):
    lock, action = bound
    expected_used = 0
    def observe():
        assert AttemptLock(lock.db_path).state("task", "post-action")["used"] == expected_used
    transport.on_connect = staticmethod(observe)
    decisions = []
    for expected_used in (1, 2, 3):
        decisions.append(action.send(b"effect"))
    refused = action.send(b"must not dispatch")
    assert [d["attempt_number"] for d in decisions] == [1, 2, 3]
    assert all(d["http"]["outcome"] == "SUCCESS" for d in decisions)
    assert len(transport.connections) == len(transport.requests) == len(transport.closed) == 3
    assert transport.requests == [("POST", "/action?q=1", b"effect",
                                   {"Content-Type": "application/octet-stream"})] * 3
    assert (refused["outcome"], refused["next_step"], refused["dispatch_attempted"], refused["http"]) == (
        "STOP", "ASK_HUMAN", False, None)
    json.dumps(decisions + [refused])


@pytest.mark.parametrize("fault", ["constructor", "request", "response", "read"])
def test_transport_failure_consumes_without_retry_or_refund(tmp_path, transport, fault):
    lock = AttemptLock(tmp_path / "authority.db")
    lock.create("task", "post-action", 1)
    action = AttemptHTTPAction(lock, "task", "post-action", "http://example.invalid/")
    transport.fault_at = fault
    failed = action.send()
    assert failed["outcome"] == "ALLOW" and failed["dispatch_attempted"]
    assert failed["http"]["outcome"] == "TRANSPORT_ERROR"
    assert lock.state("task", "post-action")["used"] == 1
    assert action.send()["outcome"] == "STOP"
    assert len(transport.connections) == 1
    assert len(transport.closed) == (0 if fault == "constructor" else 1)


@pytest.mark.parametrize("status", [200, 201, 204, 307, 401, 429, 503])
def test_http_status_never_causes_followup_dispatch(bound, transport, status):
    lock, action = bound
    transport.status = status
    result = action.send()
    assert result["http"]["status_code"] == status
    assert result["http"]["outcome"] == ("SUCCESS" if status < 300 else "HTTP_ERROR")
    assert lock.state("task", "post-action")["used"] == 1
    assert len(transport.requests) == 1


def test_reopen_and_duplicate_creation_cannot_reset_http_authority(bound, transport):
    lock, action = bound
    for _ in range(3):
        action.send()
    reopened = AttemptLock(lock.db_path)
    with pytest.raises(AuthorityAlreadyExists):
        reopened.create("task", "post-action", 999)
    result = AttemptHTTPAction(reopened, "task", "post-action", action.url).send()
    assert result["reason"] == "ATTEMPT_LIMIT_EXHAUSTED"
    assert result["state"]["used"] == 3 and not result["dispatch_attempted"]
    assert len(transport.connections) == 3


@pytest.mark.parametrize("limit", [None, 0])
def test_absent_or_zero_authority_never_initializes_transport(tmp_path, transport, limit):
    lock = AttemptLock(tmp_path / "authority.db")
    if limit is not None:
        lock.create("task", "post-action", limit)
    result = AttemptHTTPAction(lock, "task", "post-action", "http://example.invalid/").send()
    assert result["outcome"] == "STOP" and not result["dispatch_attempted"]
    assert transport.connections == []


def test_unavailable_authority_stops_before_transport(bound, transport):
    lock, action = bound
    with sqlite3.connect(lock.db_path) as conn:
        conn.execute("DROP TABLE attempt_locks")
    result = action.send()
    assert result["reason"] == "AUTHORITY_STATE_UNAVAILABLE"
    assert result["outcome"] == "STOP" and transport.connections == []


def test_response_capture_is_bounded_and_binary_safe(bound, transport):
    _, action = bound
    transport.payload = b"\xff" * 70000
    result = action.send()["http"]
    assert result["body_truncated"]
    assert base64.b64decode(result["body_base64"]) == b"\xff" * 65536
    assert len(transport.requests) == len(transport.closed) == 1


def test_https_uses_https_transport_only_after_reservation(bound, transport, monkeypatch):
    lock, _ = bound
    monkeypatch.setattr("meterlock.attempt_http.http.client.HTTPSConnection", transport)
    def committed():
        assert lock.state("task", "post-action")["used"] == 1
    transport.on_connect = staticmethod(committed)
    action = AttemptHTTPAction(lock, "task", "post-action", "https://example.invalid/")
    assert transport.connections == []
    assert action.send()["http"]["outcome"] == "SUCCESS"
    assert transport.connections == [("example.invalid", None, 5.0)]


@pytest.mark.parametrize("url", ["ftp://example.invalid/a", "example.invalid/a", "http:///a",
    "http://user@example.invalid/a", "http://user:pass@example.invalid/a", "http://example.invalid/#frag",
    "http://example.invalid/#", "http://example.invalid:bad/a", "http://example.invalid:99999/a",
    "http://example.invalid/a\r\nInjected:yes", " http://example.invalid/a", None])
def test_invalid_endpoint_is_local_error_without_consumption(bound, transport, url):
    lock, _ = bound
    with pytest.raises(ValueError):
        AttemptHTTPAction(lock, "task", "post-action", url)
    assert lock.state("task", "post-action")["used"] == 0
    assert transport.connections == []


@pytest.mark.parametrize("timeout", [0, -1, True, "5", None, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected(bound, timeout):
    lock, _ = bound
    with pytest.raises(ValueError):
        AttemptHTTPAction(lock, "task", "post-action", "http://example.invalid/", timeout)


@pytest.mark.parametrize("task,action", [("", "a"), (None, "a"), ("t", " "), ("t", None)])
def test_invalid_binding_is_rejected(bound, task, action):
    lock, _ = bound
    with pytest.raises(ValueError):
        AttemptHTTPAction(lock, task, action, "http://example.invalid/")


def test_binding_cannot_be_changed_between_calls(bound):
    _, action = bound
    for field, value in [("task_id", "new-task"), ("action", "new-action"), ("url", "http://other.invalid/")]:
        with pytest.raises(FrozenInstanceError):
            setattr(action, field, value)


@pytest.mark.parametrize("body", ["text", None, bytearray(b"bytes")])
def test_invalid_body_does_not_consume_authority(bound, transport, body):
    lock, action = bound
    with pytest.raises(TypeError):
        action.send(body)
    assert lock.state("task", "post-action")["used"] == 0 and transport.connections == []


def test_concurrent_sends_dispatch_only_three_times(bound, transport):
    lock, action = bound
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(lambda _: action.send(), range(8)))
    assert sum(d["dispatch_attempted"] for d in decisions) == 3
    assert len(transport.requests) == len(transport.connections) == 3
    assert lock.state("task", "post-action")["used"] == 3


def test_real_loopback_target_and_fresh_process_proof():
    demo = Path(__file__).resolve().parents[1] / "tools" / "attempt_http_demo.py"
    child = subprocess.run([sys.executable, "-I", str(demo)], capture_output=True,
                           text=True, timeout=30, check=True)
    result = json.loads(child.stdout)
    assert result["status"] == "PASS"
    first, restarted, failures, redirect = result["process_runs"]
    assert [d["socket_connects"] for d in first["decisions"]] == [1, 1, 1, 0]
    assert first["target_requests_after"] == restarted["target_requests_after"] == 3
    assert first["pid"] != restarted["pid"] and restarted["socket_connects"] == 0
    assert restarted["duplicate_creation"] == "REFUSED"
    assert failures["state"]["exhausted"] and redirect["socket_connects"] == 1
    assert result["target_request_count"] == 6
    assert not any("refused" in r["body"] or r["path"] == "/redirected" for r in result["target_requests"])
