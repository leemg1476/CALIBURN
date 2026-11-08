"""Authenticated durable task routes. M1 identity is a fixed development principal."""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from caliburn.config import Settings
from caliburn.policy.review import ReviewPolicy
from caliburn.runtime.contracts import History, Submit, Task
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import TERMINAL, Conflict, NotFound, get_store
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.release_contracts import ReleaseDenied


def router(auth):
    api = APIRouter(prefix="/api/v1/tasks", tags=["durable tasks"])
    Auth = Annotated[Settings, Depends(auth)]

    @api.post("", response_model=Task, status_code=202)
    def submit(
        body: Submit,
        settings: Auth,
        idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
    ):
        if contains_secret([body.model_dump(), idempotency_key], platform_secrets(settings)):
            raise HTTPException(422, "Platform credentials are forbidden in task input")
        if idempotency_key:
            if body.idempotency_key and body.idempotency_key != idempotency_key:
                raise HTTPException(422, "Conflicting idempotency keys")
            body = body.model_copy(update={"idempotency_key": idempotency_key})
        try:
            return get_store(settings.database_url).submit(
                body,
                allow_capability_proposals=settings.allow_capability_proposals,
                allow_capability_checks=settings.allow_capability_checks,
                allow_factory_execution=settings.allow_factory_execution,
                allow_registry_invocation=settings.allow_registry_invocation,
            )
        except ReleaseDenied as exc:
            raise HTTPException(403, "Capability grant unavailable") from exc
        except NotFound as exc:
            raise HTTPException(404, "Workspace grant not found") from exc
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @api.get("/{task_id}", response_model=Task)
    def get(task_id: str, settings: Auth):
        try:
            return get_store(settings.database_url).get(task_id)
        except NotFound as exc:
            raise HTTPException(404, "Task not found") from exc

    @api.get("/{task_id}/reviews")
    def reviews(task_id: str, settings: Auth):
        try:
            return ReviewPolicy(get_store(settings.database_url)).views(task_id)
        except NotFound as exc:
            raise HTTPException(404, "Task not found") from exc

    @api.get("/{task_id}/factory-execution-reviews")
    def factory_reviews(task_id: str, settings: Auth):
        try:
            result = Qualification(get_store(settings.database_url)).views(task_id)
            if contains_secret(result, platform_secrets(settings)):
                raise HTTPException(502, "Forbidden credential material")
            return result
        except NotFound as exc:
            raise HTTPException(404, "Task not found") from exc

    @api.get("/{task_id}/history", response_model=History)
    def history(
        task_id: str,
        settings: Auth,
        after_step: int = Query(0, ge=0),
        run_offset: int = Query(0, ge=0, le=100000),
        limit: int = Query(50, ge=1, le=100),
    ):
        try:
            data = get_store(settings.database_url).history(task_id, after_step, run_offset, limit)
            if contains_secret(data, platform_secrets(settings)):
                raise HTTPException(502, "History contains forbidden credential material")
            return data
        except NotFound as exc:
            raise HTTPException(404, "Task not found") from exc

    @api.post("/{task_id}/{action}", response_model=Task)
    def control(task_id: str, action: str, settings: Auth):
        if action not in {"pause", "cancel", "resume"}:
            raise HTTPException(404, "Unknown action")
        try:
            return get_store(settings.database_url).control(task_id, action)
        except NotFound as exc:
            raise HTTPException(404, "Task not found") from exc
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @api.get("/{task_id}/events")
    async def stream(
        task_id: str,
        request: Request,
        settings: Auth,
        last_event_id: Annotated[str | None, Header()] = None,
        after: int = Query(0, ge=0),
        follow: bool = True,
    ):
        try:
            cursor = int(last_event_id) if last_event_id is not None else after
            if cursor < 0:
                raise ValueError()
        except ValueError as exc:
            raise HTTPException(422, "Invalid event cursor") from exc
        store = get_store(settings.database_url)
        try:
            task = await run_in_threadpool(store.get, task_id)
        except NotFound as exc:
            raise HTTPException(404, "Task not found") from exc
        if cursor > task["sequence"]:
            raise HTTPException(409, "Event cursor is ahead of task")

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                batch = await run_in_threadpool(store.replay, task_id, cursor)
                for event in batch:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                if len(batch) == 500:
                    continue
                current = await run_in_threadpool(store.get, task_id)
                # Never exit if a terminal event committed between replay and status read.
                if (not follow or current["state"] in TERMINAL) and cursor >= current["sequence"]:
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return api
