"""Interactive local browser qualification fixture. PostgreSQL required; no paid inference.

Commands: run, restart, new, approval, xss, evidence, audit, stop. Separate API/worker.
All service identity/source/model data is synthetic development fixture data.
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import get_store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", help="Existing fixture task for continued browser checks")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url.startswith("postgresql+") or not settings.api_token:
        raise SystemExit("Set isolated PostgreSQL and fixture API token")
    store = get_store(settings.database_url)
    with socket.socket() as socket_fixture:
        socket_fixture.bind(("127.0.0.1", 0))
        port = socket_fixture.getsockname()[1]
    env = dict(os.environ, CALIBURN_PROVIDER="fixture")
    server = None
    task = (
        store.get(args.task)
        if args.task
        else store.submit(
            Submit(
                prompt="sum 17 25 · UI 검증 <img src=x onerror=alert(1)>",
                limits={"timeout_seconds": 300},
            )
        )
    )
    fixtures = [task["id"]]

    def launch():
        child = subprocess.Popen(
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
        until = time.monotonic() + 20
        while time.monotonic() < until:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                    return child
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        child.terminate()
        child.wait(5)
        raise RuntimeError("Fixture API startup failed")

    def stop(child):
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(5)

    try:
        server = launch()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{port}/tasks/ui#task={task['id']}",
                    "task_id": task["id"],
                }
            ),
            flush=True,
        )
        for line in sys.stdin:
            command = line.strip()
            if command == "stop":
                break
            if command == "restart":
                stop(server)
                server = launch()
                print("API restarted with durable task/event state preserved", flush=True)
            elif command == "run":
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--worker-once"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=False,
                )
                print(
                    json.dumps(
                        {"worker_exit": result.returncode, "state": store.get(task["id"])["state"]}
                    ),
                    flush=True,
                )
            elif command == "new":
                task = store.submit(Submit(prompt="UI cancel fixture · never dispatched"))
                fixtures.append(task["id"])
                print(json.dumps({"task_id": task["id"]}), flush=True)
            elif command == "approval":
                import hashlib

                from caliburn.policy.contracts import ReviewArgs
                from caliburn.policy.review import ReviewPolicy
                from caliburn.sandbox.contracts import Bundle, Operation, Result
                from caliburn.sandbox.queue import WorkspaceQueue
                from caliburn.sandbox.runner import run

                queue = WorkspaceQueue(store)
                source = "def total(a,b): return a-b\n"
                wid = queue.register(
                    Bundle(files={"calc.py": source}), propose_patch=True, request_review=True
                )
                plan = ReviewPolicy(store).register_plan(
                    wid, {"test_calc.py": "# inert UI plan fixture\n"}, "sha256:" + "a" * 64
                )
                task = store.submit(Submit(prompt="독립 검토 대기 · UI fixture", workspace_ref=wid))
                fixtures.append(task["id"])
                lease = store.claim("ui-review-fixture", 30)
                assert lease["id"] == task["id"]
                step = store.prepare(task["id"], lease["lease_token"], "TOOL", {})
                operation = Operation(
                    tool="repo_patch",
                    arguments={
                        "path": "calc.py",
                        "expected_sha256": hashlib.sha256(source.encode()).hexdigest(),
                        "old": "a-b",
                        "new": "a+b",
                    },
                )
                queue.request(task["id"], lease["lease_token"], step["id"], operation)
                job = queue.claim("sha256:" + "a" * 64)
                queue.finish(
                    job,
                    Result.model_validate(
                        run(
                            {
                                "files": job["files"],
                                "digest": job["digest"],
                                "operation": job["operation"],
                            }
                        )
                    ),
                )
                result = queue.poll(task["id"], lease["lease_token"], job["id"])
                store.commit(
                    task["id"],
                    lease["lease_token"],
                    step["id"],
                    {
                        "role": "tool",
                        "name": "repo_patch",
                        "content": json.dumps(result.model_dump()),
                    },
                )
                ReviewPolicy(store).ensure(
                    task["id"],
                    lease["lease_token"],
                    ReviewArgs(candidate_ref=result.candidate_ref, plan_ref=plan),
                    "a" * 64,
                )
                print(
                    json.dumps({"task_id": task["id"], "state": store.get(task["id"])["state"]}),
                    flush=True,
                )
            elif command == "xss":
                task = store.submit(Submit(prompt="Literal result fixture"))
                fixtures.append(task["id"])
                lease = store.claim("ui-literal-fixture", 30)
                assert lease["id"] == task["id"]
                step = store.prepare(task["id"], lease["lease_token"], "MODEL", {})
                store.commit(
                    task["id"],
                    lease["lease_token"],
                    step["id"],
                    {
                        "role": "assistant",
                        "content": "<img src=x onerror=alert(1)><script>window.bad=true</script>",
                    },
                    True,
                )
                print(json.dumps({"task_id": task["id"]}), flush=True)
            elif command == "audit":
                data = [
                    {
                        "task_id": tid,
                        "state": store.get(tid)["state"],
                        "history": store.history(tid),
                        "events": store.replay(tid),
                    }
                    for tid in fixtures
                ]
                Path("docs/evidence/m1-timeline-controls.json").write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
                print(json.dumps({"fixture_states": [row["state"] for row in data]}), flush=True)
            elif command == "evidence":
                final = store.get(task["id"])
                history = store.history(task["id"])
                report = {
                    "inference": "fixture (mock)",
                    "database": "PostgreSQL",
                    "transport": "actual browser/HTTP/SSE and separate API/worker",
                    "task_id": task["id"],
                    "state": final["state"],
                    "result": final["result"],
                    "model_calls": final["model_calls"],
                    "tool_calls": final["tool_calls"],
                    "history": history,
                    "events": store.replay(task["id"]),
                }
                Path("docs/evidence/m1-timeline-browser.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                print(
                    json.dumps(
                        {
                            "state": final["state"],
                            "event_count": len(report["events"]),
                            "steps": len(history["steps"]),
                        }
                    ),
                    flush=True,
                )
    finally:
        stop(server)
        store.engine.dispose()


if __name__ == "__main__":
    if "--worker-once" in sys.argv:
        from caliburn.llm import create_model
        from caliburn.runtime.worker import Worker

        settings = get_settings()
        asyncio.run(Worker(get_store(settings.database_url), create_model(settings)).run_once())
    else:
        main()
