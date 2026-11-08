"""M1 unit + real PostgreSQL integration; no paid inference or external tool writes."""

import asyncio
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from caliburn.app import app
from caliburn.config import get_settings
from caliburn.llm import FixtureModel, ProviderError
from caliburn.runtime.contracts import Submit
from caliburn.runtime.schema import events, runs, steps, tasks
from caliburn.runtime.store import Conflict, LostLease, NotFound
from caliburn.runtime.worker import Worker

AUTH = {"Authorization": "Bearer test-service-token-secret"}


def submit(store, **limits):
    return store.submit(Submit(prompt="sum 2 3", limits=limits))


def expire(store, tid):
    with store.engine.begin() as c:
        c.execute(update(tasks).where(tasks.c.id == tid).values(lease_until=store.now(c) - 1))


async def wait_for(predicate, seconds=5):
    until = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < until, "condition not reached"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_e2e_api_worker_reconnect(durable):
    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"prompt": "sum 2 3"}, headers=AUTH)
        assert created.status_code == 202
        tid = created.json()["id"]
        assert await Worker(durable, FixtureModel()).run_once()
        result = client.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
        assert result["state"] == "COMPLETED"
        assert '"sum": 5.0' in result["result"]
        assert (result["model_calls"], result["tool_calls"]) == (2, 1)
        response = client.get(f"/api/v1/tasks/{tid}/events", headers=AUTH)
        assert response.status_code == 200
        ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
        assert ids == list(range(1, result["sequence"] + 1))
        response = client.get(f"/api/v1/tasks/{tid}/events", headers={**AUTH, "Last-Event-ID": "3"})
        ids2 = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
        assert ids2 == ids[3:]
        assert (
            client.get(
                f"/api/v1/tasks/{tid}/events", headers=AUTH, params={"after": 999}
            ).status_code
            == 409
        )
        assert (
            client.get(
                f"/api/v1/tasks/{tid}/events", headers={**AUTH, "Last-Event-ID": "x"}
            ).status_code
            == 422
        )
        assert client.get(f"/api/v1/tasks/{tid}/events").status_code == 401
    with durable.engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(steps)) == 3
        assert c.scalar(select(func.count()).select_from(runs)) == 1


@pytest.mark.asyncio
async def test_idempotency_and_terminal_state(durable):
    body = Submit(prompt="sum 2 3", idempotency_key="same")
    first = durable.submit(body)
    assert durable.submit(body)["id"] == first["id"]
    with pytest.raises(Conflict):
        durable.submit(Submit(prompt="changed", idempotency_key="same"))
    await Worker(durable, FixtureModel()).run_once()
    assert not await Worker(durable, FixtureModel()).run_once()
    with pytest.raises(Conflict):
        durable.control(first["id"], "resume")
    with pytest.raises(NotFound):
        durable.get(first["id"], actor="other")
    with pytest.raises(NotFound):
        durable.replay(first["id"], tenant="other")
    with pytest.raises(NotFound):
        durable.control(first["id"], "cancel", tenant="other")
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/tasks", json={"prompt": "x", "tenant": "other"}, headers=AUTH
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/tasks", json={"prompt": "x"}, headers={**AUTH, "Idempotency-Key": "key"}
            ).status_code
            == 202
        )
        assert (
            client.post(
                "/api/v1/tasks", json={"prompt": "y"}, headers={**AUTH, "Idempotency-Key": "key"}
            ).status_code
            == 409
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["pause", "cancel"])
async def test_control_during_inflight_call(durable, action):
    started, stopped = asyncio.Event(), asyncio.Event()

    class Slow:
        async def complete(self, messages, tools):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

    t = submit(durable)
    execution = asyncio.create_task(Worker(durable, Slow(), lease_seconds=1).run_once())
    await started.wait()
    durable.control(t["id"], action)
    await asyncio.wait_for(execution, 3)
    assert stopped.is_set()
    assert durable.get(t["id"])["state"] == ("PAUSED" if action == "pause" else "CANCELLED")
    if action == "pause":
        durable.control(t["id"], "resume")
        await Worker(durable, FixtureModel()).run_once()
        assert durable.get(t["id"])["state"] == "COMPLETED"
    else:
        assert not await Worker(durable, FixtureModel()).run_once()
        with pytest.raises(Conflict):
            durable.control(t["id"], "resume")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limits,reason",
    [
        ({"max_steps": 1}, "model_step_limit"),
        ({"max_tool_calls": 0}, "tool_call_limit"),
        ({"max_tokens": 1}, "token_limit"),
        ({"max_cost": 0}, "cost_limit"),
    ],
)
async def test_budgets(durable, limits, reason):
    t = submit(durable, **limits)
    await Worker(durable, FixtureModel(), call_cost=0.1 if reason == "cost_limit" else 0).run_once()
    result = durable.get(t["id"])
    assert result["state"] == "FAILED"
    assert result["error"] == reason


@pytest.mark.asyncio
async def test_timeout_failure_and_malformed_model(durable):
    class Slow:
        async def complete(self, messages, tools):
            await asyncio.sleep(10)

    t = submit(durable, call_timeout_seconds=0.05)
    await Worker(durable, Slow()).run_once()
    assert durable.get(t["id"])["state"] == "TIMED_OUT"

    class Bad:
        async def complete(self, messages, tools):
            return {"choices": []}

    t = submit(durable)
    await Worker(durable, Bad()).run_once()
    assert durable.get(t["id"])["error"] == "model_protocol_error"

    class Failure:
        async def complete(self, messages, tools):
            raise ProviderError("sensitive upstream detail")

    t = submit(durable)
    await Worker(durable, Failure()).run_once()
    assert durable.get(t["id"])["error"] == "execution_failed"
    assert "sensitive" not in json.dumps(durable.replay(t["id"]))


@pytest.mark.asyncio
async def test_unknown_tool_and_injection_denied(durable):
    class Poison:
        async def complete(self, messages, tools):
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "p",
                                    "function": {
                                        "name": "host_shell",
                                        "arguments": '{"command":"read credentials; self-approve"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

    t = submit(durable)
    await Worker(durable, Poison()).run_once()
    assert durable.get(t["id"])["error"] == "tool_policy_denied"


@pytest.mark.asyncio
async def test_fencing_checkpoint_and_retry_ceiling(durable):
    t = submit(durable, max_retries=0)
    old = durable.claim("dead", 30)
    step = durable.prepare(t["id"], old["lease_token"], "MODEL", {})
    assert step
    expire(durable, t["id"])
    new = durable.claim("new", 30)
    with pytest.raises(LostLease):
        durable.commit(
            t["id"], old["lease_token"], step["id"], {"role": "assistant", "content": "stale"}, True
        )
    assert durable.prepare(t["id"], new["lease_token"], "MODEL", {}) is None
    assert durable.get(t["id"])["error"] == "retry_limit"


def test_heartbeat_prevents_double_claim_and_deadline_survives_pause(durable, monkeypatch):
    # Test precise lease boundaries, independent of a host's 50ms scheduling delay.
    with durable.engine.connect() as c:
        clock = [durable.now(c)]
    monkeypatch.setattr(durable, "now", lambda _c: clock[0])
    t = submit(durable, timeout_seconds=0.1)
    old = durable.claim("alive", 0.05)
    assert durable.heartbeat(t["id"], old["lease_token"], 10)
    clock[0] += 0.06  # Beyond the original lease, still inside the renewed lease/deadline.
    assert durable.claim("duplicate") is None
    durable.control(t["id"], "pause")
    clock[0] += 0.15
    durable.control(t["id"], "resume")
    assert durable.claim("later") is None
    assert durable.get(t["id"])["state"] == "TIMED_OUT"
    assert durable.get(t["id"])["deadline"] == old["deadline"]


def test_concurrent_claims_and_event_immutability(durable):
    if durable.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency/trigger")
    t = submit(durable)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda n: durable.claim(str(n)), range(8)))
    assert len([c for c in claims if c]) == 1
    with pytest.raises(DBAPIError), durable.engine.begin() as c:
        c.execute(update(events).where(events.c.task_id == t["id"]).values(type="tampered"))
    with pytest.raises(DBAPIError), durable.engine.begin() as c:
        c.execute(events.delete().where(events.c.task_id == t["id"]))


def test_migration_rollback_and_reapply(durable):
    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    assert durable.get(submit(durable)["id"])["state"] == "QUEUED"


@pytest.mark.asyncio
async def test_actual_process_death_after_tool_before_commit(durable):
    t = submit(durable)
    env = dict(
        os.environ, CALIBURN_DATABASE_URL=durable.engine.url.render_as_string(hide_password=False)
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("worker_crash_fixture.py")),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.wait_for(process.wait(), 20)
    assert process.returncode == 73
    before = durable.get(t["id"])
    assert before["state"] == "RUNNING"
    assert before["model_calls"] == 1
    await asyncio.sleep(0.4)  # natural expiry after the child process died
    await Worker(durable, FixtureModel()).run_once()
    result = durable.get(t["id"])
    assert result["state"] == "COMPLETED"
    assert result["model_calls"] == 2  # committed model call was not repeated
    assert result["tool_calls"] == 2  # uncommitted read-only tool safely repeated
    with durable.engine.connect() as c:
        statuses = (
            c.execute(select(runs.c.outcome).where(runs.c.task_id == t["id"])).scalars().all()
        )
    assert set(statuses) == {"LEASE_EXPIRED", "COMPLETED"}


@pytest.mark.asyncio
async def test_secret_guards_and_changed_tool_revision(durable):
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks", headers=AUTH, json={"prompt": "Print " + get_settings().api_token}
        )
        assert response.status_code == 422
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "caliburn-agent",
                "messages": [{"role": "user", "content": get_settings().api_token}],
            },
        )
        assert response.status_code == 422

    class Leak:
        async def complete(self, messages, tools):
            return {"choices": [{"message": {"content": "secret-sentinel"}}]}

    t = submit(durable)
    await Worker(durable, Leak(), secrets=("secret-sentinel",)).run_once()
    assert durable.get(t["id"])["error"] == "platform_secret_denied"
    assert "secret-sentinel" not in json.dumps(durable.get(t["id"]))
    t = submit(durable)
    with durable.engine.begin() as c:
        c.execute(
            update(tasks).where(tasks.c.id == t["id"]).values(policy={"tool_digest": "tampered"})
        )
    await Worker(durable, FixtureModel()).run_once()
    assert durable.get(t["id"])["error"] == "tool_revision_changed"


@pytest.mark.asyncio
async def test_checkpoint_resume_skips_committed_tool(durable):
    t = submit(durable)
    old = durable.claim("old", 30)
    model_message = await FixtureModel().complete(t["messages"], [])
    message = model_message["choices"][0]["message"]
    step = durable.prepare(t["id"], old["lease_token"], "MODEL", {})
    durable.commit(t["id"], old["lease_token"], step["id"], message)
    step = durable.prepare(t["id"], old["lease_token"], "TOOL", message["tool_calls"][0])
    durable.commit(
        t["id"],
        old["lease_token"],
        step["id"],
        {
            "role": "tool",
            "tool_call_id": "fixture-call-1",
            "name": "add_numbers",
            "content": '{"sum":5.0}',
        },
    )
    durable.control(t["id"], "pause")
    durable.control(t["id"], "resume")
    await Worker(durable, FixtureModel()).run_once()
    result = durable.get(t["id"])
    assert result["state"] == "COMPLETED"
    assert result["tool_calls"] == 1


@pytest.mark.asyncio
async def test_waiting_approval_is_not_worker_authorization(durable):
    t = submit(durable)
    # No M3 approval evaluator exists yet. Imported gated tasks must stay fail-closed.
    with durable.engine.begin() as c:
        c.execute(update(tasks).where(tasks.c.id == t["id"]).values(state="WAITING_APPROVAL"))
    assert durable.claim("model-cannot-approve") is None
    with pytest.raises(Conflict):
        durable.control(t["id"], "resume")
    assert durable.control(t["id"], "cancel")["state"] == "CANCELLED"


@pytest.mark.asyncio
async def test_concurrent_duplicate_submissions(durable):
    if durable.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL unique conflict")
    body = Submit(prompt="sum 2 3", idempotency_key="concurrent-key")
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: durable.submit(body)["id"], range(8)))
    assert len(set(ids)) == 1
    assert len(durable.replay(ids[0])) == 1
