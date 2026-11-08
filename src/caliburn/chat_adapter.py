"""OpenAI chat adapter for durable tasks, independent of the runtime worker protocol."""

import asyncio
import json
import time

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import TERMINAL, get_store


def completion(task, model):
    return {
        "id": "chatcmpl-" + task["id"],
        "object": "chat.completion",
        "created": int(task["created_at"]),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": task["result"]},
                "finish_reason": "stop",
            }
        ],
        "usage": None,
        "caliburn": {
            "task_id": task["id"],
            "mode": "durable",
            "events_url": f"/api/v1/tasks/{task['id']}/events",
        },
    }


async def wait(store, task, *, timeout=90):
    until = time.monotonic() + timeout
    while task["state"] not in TERMINAL:
        if time.monotonic() >= until:
            raise HTTPException(
                504, {"task_id": task["id"], "reason": "Task continues asynchronously"}
            )
        await asyncio.sleep(0.05)
        task = await run_in_threadpool(store.get, task["id"])
    if task["state"] != "COMPLETED":
        raise HTTPException(
            409, {"task_id": task["id"], "state": task["state"], "reason": task["error"]}
        )
    return task


async def durable_completion(request, settings):
    prompt = "\n".join(str(message.get("content") or "") for message in request.messages)
    if not 1 <= len(prompt) <= 20000:
        raise HTTPException(422, "Durable chat context must be 1..20000 characters")
    store = get_store(settings.database_url)
    task = await run_in_threadpool(
        store.submit,
        Submit(
            prompt=prompt,
            limits={"max_steps": settings.max_steps, "max_cost": settings.task_max_cost},
        ),
        allow_capability_proposals=settings.allow_capability_proposals,
        allow_capability_checks=settings.allow_capability_checks,
        allow_factory_execution=settings.allow_factory_execution,
    )
    if not request.stream:
        return completion(await wait(store, task), request.model)

    def chunk(delta, finish=None, **extra):
        return {
            "id": "chatcmpl-" + task["id"],
            "object": "chat.completion.chunk",
            "created": int(task["created_at"]),
            "model": request.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            **extra,
        }

    async def generate():
        # This is chat-protocol compatibility, not upstream token streaming.
        # Task event progress/replay remains the authenticated task SSE endpoint.
        meta = {
            "task_id": task["id"],
            "mode": "durable",
            "events_url": f"/api/v1/tasks/{task['id']}/events",
        }
        yield "data: " + json.dumps(chunk({"role": "assistant"}, caliburn=meta)) + "\n\n"
        try:
            final = await wait(store, task)
            yield (
                "data: "
                + json.dumps(chunk({"content": final["result"]}), ensure_ascii=False)
                + "\n\n"
            )
            yield "data: " + json.dumps(chunk({}, "stop", caliburn=meta)) + "\n\n"
        except HTTPException as exc:
            # Headers have been sent. Emit a bounded error frame with task reference.
            yield (
                "data: "
                + json.dumps(
                    {
                        "error": {
                            "message": "Durable task did not complete",
                            "type": "caliburn_task_error",
                            "task_id": task["id"],
                            "detail": exc.detail,
                        }
                    }
                )
                + "\n\n"
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
