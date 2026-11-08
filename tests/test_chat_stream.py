"""OpenAI-compatible streaming frames over a real durable task, with mocked inference."""

import asyncio
import json

import httpx
import pytest

from caliburn.app import app
from caliburn.llm import FixtureModel
from caliburn.runtime.worker import Worker

AUTH = {"Authorization": "Bearer test-service-token-secret"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_durable_chat_stream_contract_and_error(durable, failure):
    class BrokenFixture:
        async def complete(self, messages, tools):
            return {"choices": []}

    pump = asyncio.create_task(
        Worker(durable, BrokenFixture() if failure else FixtureModel()).serve()
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(
                client.post(
                    "/v1/chat/completions",
                    headers=AUTH,
                    json={
                        "model": "caliburn-agent-durable",
                        "stream": True,
                        "messages": [{"role": "user", "content": "sum 2 3"}],
                    },
                ),
                10,
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
            assert lines[-1] == "[DONE]"
            frames = [json.loads(line) for line in lines[:-1]]
            tid = frames[0]["caliburn"]["task_id"]
            assert frames[0]["choices"][0]["delta"] == {"role": "assistant"}
            task = durable.get(tid)
            if failure:
                assert task["state"] == "FAILED"
                assert frames[-1]["error"]["task_id"] == tid
                assert frames[-1]["error"]["type"] == "caliburn_task_error"
            else:
                assert task["state"] == "COMPLETED"
                assert '"sum": 5.0' in frames[1]["choices"][0]["delta"]["content"]
                assert frames[-1]["choices"][0]["finish_reason"] == "stop"
                replay = await client.get(
                    frames[0]["caliburn"]["events_url"], headers={**AUTH, "Last-Event-ID": "3"}
                )
                ids = [
                    int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")
                ]
                assert ids == list(range(4, task["sequence"] + 1))
    finally:
        pump.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pump


@pytest.mark.asyncio
async def test_stream_auth_and_input_are_checked_before_headers(durable):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {
            "model": "caliburn-agent-durable",
            "stream": True,
            "messages": [{"role": "user", "content": "sum 2 3"}],
        }
        assert (await client.post("/v1/chat/completions", json=body)).status_code == 401
        body["messages"][0]["role"] = "administrator"
        assert (
            await client.post("/v1/chat/completions", headers=AUTH, json=body)
        ).status_code == 422
