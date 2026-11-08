"""Read real persisted release/task evidence over loopback HTTP; no model calls."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def run(args):
    proof = json.loads(Path(args.proof).read_text(encoding="utf-8"))
    token = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(
        os.environ,
        CALIBURN_PROVIDER="fixture",
        CALIBURN_API_TOKEN=token,
        CALIBURN_ALLOW_REGISTRY_INVOCATION="false",
    )
    for key in ("CALIBURN_API_ENV_FILE", "CALIBURN_UPSTREAM_API_KEY", "OPENAI_API_KEY"):
        env.pop(key, None)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "caliburn.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            for _ in range(100):
                try:
                    if client.get("/healthz").status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                raise ValueError("Loopback API did not start")
            assert client.get("/api/v1/registry").status_code == 401
            headers = {"Authorization": "Bearer " + token}
            catalog = client.get("/api/v1/registry", headers=headers)
            catalog.raise_for_status()
            metrics = client.get("/api/v1/registry/metrics", headers=headers)
            metrics.raise_for_status()
            receipts = []
            for item in proof["reuse"]:
                base = "/api/v1/tasks/" + item["task_id"]
                task = client.get(base, headers=headers)
                history = client.get(base + "/history", headers=headers)
                events = client.get(base + "/events?follow=false", headers=headers)
                task.raise_for_status()
                history.raise_for_status()
                events.raise_for_status()
                assert task.json()["state"] == "COMPLETED"
                assert any(
                    s["tool_name"] == "monthly_region_sales" for s in history.json()["steps"]
                )
                assert "REGISTERED_TOOL_QUEUED" in events.text
                receipts.append(
                    {
                        "task_id": item["task_id"],
                        "state": task.json()["state"],
                        "history_steps": history.json()["steps"],
                        "sse_registered_tool_event": True,
                    }
                )
            result = {
                "real_http": True,
                "paid_calls": 0,
                "unauthenticated_status": 401,
                "catalog": catalog.json(),
                "metrics": metrics.json(),
                "tasks": receipts,
                "fixture_provider_used_for_read_only_api": True,
                "persisted_task_model": proof["real_model"],
            }
            Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(
                json.dumps({"real_http": True, "completed_tasks": len(receipts), "paid_calls": 0})
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--proof", required=True)
    p.add_argument("--output", required=True)
    run(p.parse_args())


if __name__ == "__main__":
    main()
