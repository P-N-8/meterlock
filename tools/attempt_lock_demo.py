"""Offline 3-attempt proof with separate Python processes; standard library only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def network_guard(event, args):
    if event.startswith("socket."):
        raise RuntimeError("Network forbidden in Attempt Lock demo")


sys.addaudithook(network_guard)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from meterlock.attempt_lock import AttemptLock, AuthorityAlreadyExists


def require(ok):
    if not ok:
        raise RuntimeError("Attempt Lock demo failed")


def worker(phase, directory):
    store = AttemptLock(directory / "authority.db")
    effects = directory / "executions.jsonl"
    recreated = None
    if phase == "first":
        store.create("task-3", "simulated-action", 3)
    else:
        try:
            store.create("task-3", "simulated-action", 3)
        except AuthorityAlreadyExists:
            recreated = "REFUSED"
        else:
            raise RuntimeError("Restart recreated exhausted authority")

    def simulated_action():
        state = AttemptLock(directory / "authority.db").state("task-3", "simulated-action")
        with effects.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"attempt": state["used"], "pid": os.getpid()}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return "simulated action executed"

    decisions = [store.run("task-3", "simulated-action", simulated_action)
                 for _ in range(4 if phase == "first" else 1)]
    return {"phase": phase, "pid": os.getpid(), "recreate_after_restart": recreated,
            "decisions": decisions, "state": store.state("task-3", "simulated-action")}


def demonstrate():
    with tempfile.TemporaryDirectory(prefix="meterlock-attempt-demo-") as directory:
        phases = []
        for phase in ("first", "after-restart"):
            child = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()),
                                    "--phase", phase, "--directory", directory],
                                   capture_output=True, text=True, timeout=30, check=True)
            phases.append(json.loads(child.stdout))
        effects = [json.loads(line) for line in (Path(directory) / "executions.jsonl").read_text().splitlines()]
        first, restarted = phases
        require([d["outcome"] for d in first["decisions"]] == ["ALLOW", "ALLOW", "ALLOW", "STOP"])
        require([d["executed"] for d in first["decisions"]] == [True, True, True, False])
        require(first["decisions"][3]["next_step"] == "ASK_HUMAN")
        require(restarted["decisions"][0]["outcome"] == "STOP")
        require(restarted["decisions"][0]["next_step"] == "ASK_HUMAN")
        require(restarted["decisions"][0]["executed"] is False)
        require(restarted["state"] == first["state"])
        require(restarted["state"]["used"] == 3 and restarted["state"]["exhausted"])
        require([e["attempt"] for e in effects] == [1, 2, 3])
        return {"status": "PASS", "proof": "three executions; fourth and post-restart attempts refused",
                "process_runs": phases, "simulated_effects": effects,
                "gateway_started": False, "api_key_used": False, "paid_requests": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["first", "after-restart"])
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.phase:
        if args.directory is None:
            parser.error("--directory is required with --phase")
        result = worker(args.phase, args.directory)
    else:
        result = demonstrate()
    print(json.dumps(result, indent=2))
