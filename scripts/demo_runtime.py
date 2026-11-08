"""Live socket demo against a migrated PostgreSQL database, with an offline fixture LLM.
Starts and stops its own API and worker child processes; emits sanitized evidence JSON.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main():
    token = os.environ.get("CALIBURN_API_TOKEN")
    if not token:
        raise SystemExit("Set CALIBURN_API_TOKEN")
    # The ephemeral port is local to this test. Nothing is exposed off-host.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, CALIBURN_PROVIDER="fixture")
    children = []
    try:
        for args in (
            [
                sys.executable,
                "-m",
                "uvicorn",
                "caliburn.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            [sys.executable, "-m", "caliburn.runtime.worker"],
        ):
            children.append(
                subprocess.Popen(
                    args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            )
        with httpx.Client(
            base_url=base, timeout=20, headers={"Authorization": "Bearer " + token}
        ) as client:
            until = time.monotonic() + 20
            while True:
                try:
                    if client.get("/healthz").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                if time.monotonic() > until:
                    raise RuntimeError("API startup timeout")
                time.sleep(0.1)
            result = client.post(
                "/v1/chat/completions",
                json={
                    "model": "caliburn-agent-durable",
                    "messages": [{"role": "user", "content": "sum 2 3"}],
                },
            )
            result.raise_for_status()
            data = result.json()
            tid = data["caliburn"]["task_id"]
            task = client.get("/api/v1/tasks/" + tid).json()
            assert task["state"] == "COMPLETED"
            assert '"sum": 5.0' in task["result"]
            # Read a prefix from a live socket, disconnect, reconnect from last event.
            prefix = []
            with client.stream("GET", f"/api/v1/tasks/{tid}/events") as stream:
                for line in stream.iter_lines():
                    if line.startswith("id: "):
                        prefix.append(int(line[4:]))
                    if len(prefix) == 3:
                        break
            replay = client.get(
                f"/api/v1/tasks/{tid}/events", headers={"Last-Event-ID": str(prefix[-1])}
            )
            suffix = [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")]
            assert prefix + suffix == list(range(1, task["sequence"] + 1))
            evidence = {
                "transport": "real HTTP sockets",
                "inference": "offline fixture (mock)",
                "persistence": "PostgreSQL",
                "task_id": tid,
                "state": task["state"],
                "model_calls": task["model_calls"],
                "tool_calls": task["tool_calls"],
                "sse_prefix": prefix,
                "sse_reconnected": suffix,
                "verified_sum": 5.0,
            }
            path = Path("docs/evidence/m1-live-demo.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence))
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(5)


if __name__ == "__main__":
    main()
