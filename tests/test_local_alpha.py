import json
from pathlib import Path
import subprocess
import sys

import pytest

from meterlock.attempt_lock import AuthorityAlreadyExists
from meterlock.local_alpha import ACTION, AlphaState


def test_ui_authorities_persist_and_duplicate_creation_cannot_reset(tmp_path):
    state = AlphaState(tmp_path)
    state.create("Draft check", 3)
    state.attempts.reserve("Draft check", ACTION)
    reopened = AlphaState(tmp_path)
    assert reopened.snapshot()["selected"] == "Draft check"
    assert reopened.attempts.state("Draft check", ACTION)["used"] == 1
    with pytest.raises(AuthorityAlreadyExists):
        reopened.create("Draft check", 99)
    assert reopened.attempts.state("Draft check", ACTION)["max_attempts"] == 3
    assert len(reopened.snapshot()["authorities"]) == 2


def test_exhausted_ui_action_records_stop_without_transport(tmp_path, monkeypatch):
    state = AlphaState(tmp_path)
    for _ in range(3):
        state.attempts.reserve("First task", ACTION)
    def forbidden(*args, **kwargs):
        pytest.fail("Exhausted UI action constructed HTTP transport")
    monkeypatch.setattr("meterlock.attempt_http.http.client.HTTPConnection", forbidden)
    result = state.run_action("First task", "http://127.0.0.1:12345/local-action", "test-marker")
    assert (result["outcome"], result["next_step"], result["dispatch_attempted"]) == ("STOP", "ASK_HUMAN", False)
    assert state.snapshot()["history"][0]["outcome"] == "blocked"
    reopened = AlphaState(tmp_path)
    assert reopened.attempts.state("First task", ACTION)["used"] == 3
    assert reopened.snapshot()["history"] == state.snapshot()["history"]


def test_sample_wallet_uses_existing_finite_ledger_and_survives_reopen(tmp_path):
    state = AlphaState(tmp_path)
    assert [state.sample_spend()["outcome"] for _ in range(6)] == ["ALLOW"] * 5 + ["STOP"]
    wallet = state.snapshot()["wallet"]
    assert wallet == {"budget": "$1.00", "spent": "$1.00", "remaining": "$0.00", "held": "$0.00", "status": "exhausted"}
    reopened = AlphaState(tmp_path)
    assert reopened.snapshot()["wallet"] == wallet
    assert len(reopened.wallet.list_states()) == 1
    assert reopened.sample_spend()["outcome"] == "STOP"


def test_failed_transport_is_visible_as_failure_with_used_attempt(tmp_path, monkeypatch):
    state = AlphaState(tmp_path)
    def failed(*args, **kwargs):
        raise OSError("local transport unavailable")
    monkeypatch.setattr("meterlock.attempt_http.http.client.HTTPConnection", failed)
    result = state.run_action("First task", "http://127.0.0.1:12345/local-action", "test-marker")
    assert result["result"] == "failed" and result["dispatch_attempted"]
    assert state.attempts.state("First task", ACTION)["used"] == 1
    assert state.snapshot()["history"][0]["outcome"] == "failed"


def test_interrupted_history_never_claims_success_or_refunds(tmp_path):
    state = AlphaState(tmp_path)
    state.event("First task", "attempt")
    state.attempts.reserve("First task", ACTION)
    reopened = AlphaState(tmp_path)
    activity = reopened.snapshot()["history"][0]
    assert activity["outcome"] == "pending" and "unconfirmed" in activity["message"]
    assert reopened.attempts.state("First task", ACTION)["used"] == 1


@pytest.mark.parametrize("name,limit", [("", 3), ("x\n", 3), ("x" * 81, 3), (None, 3), ("x", True), ("x", 0), ("x", 101)])
def test_visible_form_validation_does_not_create_authority(tmp_path, name, limit):
    state = AlphaState(tmp_path)
    with pytest.raises(ValueError):
        state.create(name, limit)
    assert len(state.snapshot()["authorities"]) == 1


def test_visible_layer_real_http_and_abrupt_process_restart():
    demo = Path(__file__).resolve().parents[1] / "tools/visible_alpha_demo.py"
    child = subprocess.run([sys.executable, "-I", str(demo)], capture_output=True, text=True, check=True, timeout=30)
    proof = json.loads(child.stdout)
    assert proof["status"] == "PASS"
    assert proof["outbound_http_connects"] == 3
    assert proof["target_committed_counts"] == [1, 2, 3]
    assert proof["state_before_restart"] == proof["state_after_restart"]
    assert proof["post_restart_decision"]["outcome"] == "STOP"
