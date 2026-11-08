"""Actual authenticated history projection and inert console asset boundary."""

import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from caliburn.app import app
from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import NotFound
from caliburn.runtime.worker import Worker

AUTH = {"Authorization": "Bearer test-service-token-secret"}


def test_console_assets_are_inert_and_strictly_scoped():
    with TestClient(app) as client:
        page = client.get("/tasks/ui")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in page.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["x-content-type-options"] == "nosniff"
        assert "test-service-token-secret" not in page.text
        assert 'type="password"' in page.text
        for name in ("timeline.css", "timeline.mjs", "stream.mjs"):
            asset = client.get("/tasks/assets/" + name)
            assert asset.status_code == 200
            assert "test-service-token-secret" not in asset.text
        assert client.get("/tasks/assets/app.py").status_code == 404
        assert client.get("/tasks/assets/%2e%2e%2fapp.py").status_code == 404
        js = client.get("/tasks/assets/timeline.mjs").text
        assert "innerHTML" not in js and "localStorage" not in js and "sessionStorage" not in js


@pytest.mark.asyncio
async def test_authenticated_paginated_history_and_hashes(durable):
    task = durable.submit(Submit(prompt="literal <img src=x onerror=alert(1)>"))
    lease = durable.claim("timeline-fixture", 30)
    token = lease["lease_token"]
    output = {"role": "assistant", "content": "literal <script>window.bad=true</script>"}
    for _ in range(3):
        step = durable.prepare(task["id"], token, "MODEL", {})
        durable.commit(task["id"], token, step["id"], output)
    durable.control(task["id"], "pause")
    durable.control(task["id"], "resume")
    lease = durable.claim("timeline-second-run", 30)
    step = durable.prepare(
        task["id"],
        lease["lease_token"],
        "TOOL",
        {"function": {"name": "utc_now", "arguments": "{}"}},
    )
    with TestClient(app) as client:
        url = f"/api/v1/tasks/{task['id']}/history"
        assert client.get(url).status_code == 401
        first = client.get(url + "?limit=2", headers=AUTH).json()
        assert len(first["steps"]) == 2 and first["next_step"] == 2
        assert len(first["runs"]) == 2 and first["next_run_offset"] is None
        second = client.get(url + "?limit=2&after_step=2&run_offset=1", headers=AUTH).json()
        assert [s["ordinal"] for s in second["steps"]] == [3, 4]
        assert second["steps"][-1]["tool_name"] == "utc_now"
        assert second["steps"][-1]["status"] == "STARTED"
        assert len(second["runs"]) == 1
        assert second["next_step"] is None
        assert (
            first["steps"][0]["output_sha256"]
            == hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()
        )
        assert "<script>" not in json.dumps(first)
        for field in ("messages", "lease_token", "input", "output"):
            assert field not in first
            assert all(field not in s for s in first["steps"])
        assert client.get(url + "?limit=101", headers=AUTH).status_code == 422
        assert client.get(url + "?after_step=-1", headers=AUTH).status_code == 422
        assert client.get("/api/v1/tasks/missing/history", headers=AUTH).status_code == 404
    with pytest.raises(NotFound):
        durable.history(task["id"], actor="another", tenant="another")
    with pytest.raises(ValueError):
        durable.history(task["id"], limit=10000)


@pytest.mark.asyncio
async def test_history_read_does_not_dispatch_or_change_task(durable):
    task = durable.submit(Submit(prompt="read-only history"))
    before = durable.get(task["id"])
    history = durable.history(task["id"])
    assert history["runs"] == history["steps"] == []
    assert history["deadline"] is None
    assert durable.get(task["id"]) == before

    # A normal worker still runs afterwards; UI reads hold no worker lease.
    class Model:
        async def complete(self, messages, tools):
            return {"choices": [{"message": {"content": "ready"}}]}

    await asyncio.wait_for(Worker(durable, Model()).run_once(), 5)
    assert durable.history(task["id"])["steps"][0]["status"] == "COMPLETED"


def test_history_never_returns_known_fixture_credential(durable):
    task = durable.submit(Submit(prompt="fixture worker identifier confidentiality"))
    durable.claim("test-service-token-secret", 30)
    with TestClient(app) as client:
        result = client.get(f"/api/v1/tasks/{task['id']}/history", headers=AUTH)
        assert result.status_code == 502
        assert "test-service-token-secret" not in result.text
