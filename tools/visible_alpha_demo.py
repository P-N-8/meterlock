"""Repeatable local UI/API proof, with two actual server processes and no browser."""
import http.client
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile


def require(ok):
    if not ok:
        raise RuntimeError("Visible alpha proof failed")


def guard(event, args):
    if event == "socket.connect" and args[1][0] != "127.0.0.1":
        raise RuntimeError("External network forbidden")
    if event == "socket.getaddrinfo" and args[0] != "127.0.0.1":
        raise RuntimeError("External lookup forbidden")


sys.addaudithook(guard)

CHILD = r'''
import json, pathlib, sys
src, directory, trace = sys.argv[1:]
def guard(event,args):
    if event=='socket.bind' and args[1][0]!='127.0.0.1':
        raise RuntimeError('Loopback only')
    if event=='socket.getaddrinfo' and args[0]!='127.0.0.1':
        raise RuntimeError('External lookup forbidden')
    if event=='socket.connect':
        if args[1][0]!='127.0.0.1':
            raise RuntimeError('External target forbidden')
        with open(trace,'a') as stream: stream.write(json.dumps(args[1])+'\n')
    if event in ('socket.gethostbyname','socket.gethostbyaddr','socket.sendto'):
        raise RuntimeError('Unrelated network forbidden')
sys.addaudithook(guard)
sys.path.insert(0,src)
from meterlock.local_alpha import main
sys.argv=['meterlock.local_alpha','--no-browser','--data-dir',directory]
main()
'''


def launch(directory, trace):
    source = Path(__file__).resolve().parents[1] / "src"
    child = subprocess.Popen([sys.executable, "-I", "-c", CHILD, str(source), str(directory), str(trace)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = child.stdout.readline()
    found = re.search(r"http://127\.0\.0\.1:(\d+)", line)
    if not found:
        child.kill()
        stdout, stderr = child.communicate(timeout=5)
        raise RuntimeError("Local server did not start: " + line + stdout + stderr)
    return child, int(found.group(1))


def stop(child):
    child.terminate()
    try:
        child.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=5)


def request(port, path, value=None, token=None, host=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
    if token is not None:
        headers["X-MeterLock-UI"] = token
    if host:
        headers["Host"] = host
    try:
        connection.request("POST" if value is not None else "GET", path,
                           json.dumps(value).encode() if value is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, raw.decode() if path == "/" else json.loads(raw)
    finally:
        connection.close()


def demonstrate():
    with tempfile.TemporaryDirectory(prefix="meterlock-visible-proof-") as raw:
        directory = Path(raw)
        trace = directory / "dispatches.jsonl"
        child, port = launch(directory, trace)
        first_pid = child.pid
        try:
            status, html = request(port, "/")
            require(status == 200 and "Attempt Lock" in html and "Spend Lock" in html)
            token = re.search(r'name="ml-token" content="([a-f0-9]+)"', html).group(1)
            require(request(port, "/api/action", {"task": "First task"})[0] == 403)
            require(request(port, "/api/state", host="untrusted.example")[0] == 403)
            require(request(port, "/api/create", {"task": "Restart test", "limit": 3}, token)[0] == 200)
            outcomes = []
            for _ in range(4):
                code, body = request(port, "/api/action", {"task": "Restart test"}, token)
                require(code == 200)
                outcomes.append(body["decision"])
            require([x["outcome"] for x in outcomes] == ["ALLOW"] * 3 + ["STOP"])
            require(outcomes[-1]["next_step"] == "ASK_HUMAN" and not outcomes[-1]["dispatch_attempted"])
            require(len(trace.read_text().splitlines()) == 3)
            code, spent = request(port, "/api/spend", {}, token)
            require(code == 200 and spent["state"]["wallet"]["remaining"] == "$0.80")
            first_state = request(port, "/api/state")[1]
        finally:
            stop(child)
        child, port = launch(directory, trace)
        restarted_pid = child.pid
        try:
            token = re.search(r'name="ml-token" content="([a-f0-9]+)"', request(port, "/")[1]).group(1)
            reopened = request(port, "/api/state")[1]
            require(reopened == first_state)
            duplicate_status = request(port, "/api/create", {"task": "Restart test", "limit": 99}, token)[0]
            require(duplicate_status == 409)
            status, refused = request(port, "/api/action", {"task": "Restart test"}, token)
            require(status == 200 and refused["decision"]["outcome"] == "STOP")
            require(refused["decision"]["next_step"] == "ASK_HUMAN")
            require(not refused["decision"]["dispatch_attempted"] and len(trace.read_text().splitlines()) == 3)
            require(refused["state"]["local_actions_completed"] == 3)
            require(refused["state"]["history"][0]["outcome"] == "blocked")
        finally:
            stop(child)
        with sqlite3.connect(directory / "alpha.db") as db:
            receipt_counts = [r[0] for r in db.execute("SELECT committed_used FROM alpha_receipts ORDER BY event_id")]
            saved = db.execute("SELECT max_attempts,used FROM attempt_locks WHERE task_id='Restart test'").fetchone()
        require(receipt_counts == [1, 2, 3] and saved == (3, 3))
        return {"status": "PASS", "server_pids": [first_pid, restarted_pid],
                "first_decisions": outcomes, "duplicate_creation_http_status": duplicate_status,
                "state_before_restart": first_state, "state_after_restart": reopened,
                "post_restart_decision": refused["decision"], "outbound_http_connects": 3,
                "target_committed_counts": receipt_counts, "saved_limit_and_used": saved,
                "csrf_and_host_rejections": True, "external_action": False,
                "real_api_key_used": False, "paid_requests": 0}


if __name__ == "__main__":
    print(json.dumps(demonstrate(), indent=2))
