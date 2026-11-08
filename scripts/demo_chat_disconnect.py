"""Actual socket disconnect: chat transport closes, durable queue work continues."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from caliburn.config import get_settings


def main():
    settings = get_settings()
    if settings.provider != "fixture":
        raise SystemExit("This demo requires offline fixture provider")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    children = []
    env = dict(os.environ, CALIBURN_PROVIDER="fixture")
    try:
        children.append(
            subprocess.Popen(
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
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            timeout=10,
            headers={"Authorization": "Bearer " + settings.api_token},
        ) as client:
            deadline = time.monotonic() + 20
            while True:
                try:
                    if client.get("/healthz").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("API startup timeout")
                time.sleep(0.05)
            with client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": "caliburn-agent-durable",
                    "stream": True,
                    "messages": [{"role": "user", "content": "sum 2 3"}],
                },
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        first = json.loads(line[6:])
                        tid = first["caliburn"]["task_id"]
                        break
            before = client.get("/api/v1/tasks/" + tid).json()
            assert before["state"] == "QUEUED"
            children.append(
                subprocess.Popen(
                    [sys.executable, "-m", "caliburn.runtime.worker"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            while True:
                task = client.get("/api/v1/tasks/" + tid).json()
                if task["state"] == "COMPLETED":
                    break
                assert time.monotonic() < deadline, "Task failed to complete after disconnect"
                time.sleep(0.05)
            assert '"sum": 5.0' in task["result"]
            replay = client.get(
                first["caliburn"]["events_url"], headers={"Last-Event-ID": "1"}
            ).text
            ids = [int(line[4:]) for line in replay.splitlines() if line.startswith("id: ")]
            assert ids == list(range(2, task["sequence"] + 1))
            evidence = {
                "transport": "real HTTP sockets",
                "inference": "offline fixture (mock)",
                "task_id": tid,
                "disconnected_after_first_chat_frame": True,
                "state_after_disconnect": before["state"],
                "final_state": task["state"],
                "model_calls": task["model_calls"],
                "tool_calls": task["tool_calls"],
                "replay_ids": ids,
            }
            path = Path("docs/evidence/m1-chat-disconnect.json")
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
