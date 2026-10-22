"""Standard-library-only proof against an ephemeral loopback HTTP target.

The client workers are separate Python processes. Audit hooks allow their
outbound connections only to this exact local target; no external network.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from meterlock.attempt_http import AttemptHTTPAction
from meterlock.attempt_lock import AttemptLock, AuthorityAlreadyExists


def require(ok):
    if not ok:
        raise RuntimeError("Attempt-controlled HTTP demo failed")


def worker(phase, directory, port):
    connections = []

    def guard(event, args):
        if event == "socket.getaddrinfo":
            if args[:2] != ("127.0.0.1", port):
                raise RuntimeError("Only the exact loopback target is permitted")
        elif event == "socket.connect":
            if args[1] != ("127.0.0.1", port):
                raise RuntimeError("External network forbidden")
            connections.append({"host": args[1][0], "port": args[1][1]})
        elif event in ("socket.bind", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto"):
            raise RuntimeError("Unrelated network forbidden")

    sys.addaudithook(guard)
    lock = AttemptLock(directory / "authority.db")
    url = f"http://127.0.0.1:{port}/action"
    duplicate = None
    if phase == "first":
        lock.create("task-3", "local-http-post", 3)
        bodies = [b"one", b"two", b"three", b"refused-four"]
        task, path = "task-3", url
    elif phase == "after-restart":
        try:
            lock.create("task-3", "local-http-post", 999)
        except AuthorityAlreadyExists:
            duplicate = "REFUSED"
        else:
            raise RuntimeError("Restart reset authority")
        bodies = [b"refused-after-restart"]
        task, path = "task-3", url
    elif phase == "failures":
        lock.create("failure-task", "local-http-post", 2)
        bodies = [b"status-error", b"disconnect", b"refused-after-failures"]
        task, path = "failure-task", url + "/failure"
    else:
        lock.create("redirect-task", "local-http-post", 1)
        bodies = [b"redirect", b"refused-after-redirect"]
        task, path = "redirect-task", url + "/redirect"
    adapter = AttemptHTTPAction(lock, task, "local-http-post", path)
    decisions = []
    for body in bodies:
        before = len(connections)
        result = adapter.send(body)
        decisions.append({"decision": result, "socket_connects": len(connections) - before})
    return {"phase": phase, "pid": os.getpid(), "duplicate_creation": duplicate,
            "decisions": decisions, "state": lock.state(task, "local-http-post"),
            "socket_connects": len(connections)}


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # Avoid HTTPServer's optional reverse-DNS lookup; this proof is local only.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address


def demonstrate():
    def parent_guard(event, args):
        if event == "socket.bind" and args[1][0] != "127.0.0.1":
            raise RuntimeError("Only loopback binding is permitted")
        if event in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
                     "socket.gethostbyaddr", "socket.sendto"):
            raise RuntimeError("Parent must not make outbound network calls")

    sys.addaudithook(parent_guard)
    with tempfile.TemporaryDirectory(prefix="meterlock-http-demo-") as raw_directory:
        directory = Path(raw_directory)
        received = []
        received_lock = threading.Lock()

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                task = ("failure-task" if self.path.endswith("/failure") else
                        "redirect-task" if self.path.endswith("/redirect") else "task-3")
                state = AttemptLock(directory / "authority.db").state(task, "local-http-post")
                with received_lock:
                    received.append({"path": self.path, "body": body.decode("ascii"),
                                     "task_id": task, "committed_used_at_target": state["used"]})
                if body == b"disconnect":
                    self.close_connection = True
                    return
                code = 503 if body == b"status-error" else 307 if body == b"redirect" else 200
                self.send_response(code)
                if code == 307:
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirected")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        phases = []
        server = LocalServer(("127.0.0.1", 0), Target)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for phase in ("first", "after-restart", "failures", "redirect"):
                before = len(received)
                child = subprocess.run(
                    [sys.executable, "-I", str(Path(__file__).resolve()), "--phase", phase,
                     "--directory", str(directory), "--port", str(server.server_port)],
                    capture_output=True, text=True, check=True, timeout=20)
                result = json.loads(child.stdout)
                result["target_requests_before"] = before
                result["target_requests_after"] = len(received)
                phases.append(result)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        first, restarted, failures, redirect = phases
        require([d["decision"]["outcome"] for d in first["decisions"]] == ["ALLOW"] * 3 + ["STOP"])
        require([d["socket_connects"] for d in first["decisions"]] == [1, 1, 1, 0])
        require(all(d["decision"]["http"]["outcome"] == "SUCCESS" for d in first["decisions"][:3]))
        require(first["target_requests_after"] == 3)
        require(first["pid"] != restarted["pid"])
        require(restarted["state"] == first["state"] and restarted["state"]["exhausted"])
        require(restarted["duplicate_creation"] == "REFUSED")
        require(restarted["socket_connects"] == 0 and restarted["target_requests_after"] == 3)
        require([d["decision"]["http"]["outcome"] for d in failures["decisions"][:2]]
                == ["HTTP_ERROR", "TRANSPORT_ERROR"])
        require(failures["state"]["used"] == 2 and failures["socket_connects"] == 2)
        require(redirect["decisions"][0]["decision"]["http"]["status_code"] == 307)
        require(redirect["socket_connects"] == 1)
        for phase in phases:
            for item in phase["decisions"]:
                decision = item["decision"]
                if decision["outcome"] == "STOP":
                    require(decision["next_step"] == "ASK_HUMAN")
                    require(not decision["dispatch_attempted"] and item["socket_connects"] == 0)
        require([r["body"] for r in received] == ["one", "two", "three", "status-error", "disconnect", "redirect"])
        require([r["committed_used_at_target"] for r in received] == [1, 2, 3, 1, 2, 1])
        return {"status": "PASS", "target": "ephemeral 127.0.0.1 HTTP server",
                "process_runs": phases, "target_requests": received,
                "target_request_count": len(received), "external_network_allowed": False,
                "api_key_used": False, "paid_requests": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["first", "after-restart", "failures", "redirect"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.phase:
        if args.directory is None or args.port is None:
            parser.error("--directory and --port are required with --phase")
        output = worker(args.phase, args.directory, args.port)
    else:
        output = demonstrate()
    print(json.dumps(output, indent=2))
