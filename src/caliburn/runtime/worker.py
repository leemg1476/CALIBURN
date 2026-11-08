"""Separate async worker. Curated tools and typed isolated workspace requests; no host execution."""

import asyncio
import contextlib
import json
import os
import socket
from uuid import uuid4

from caliburn.config import get_settings
from caliburn.llm import create_model
from caliburn.policy.contracts import REVIEW_TOOL_DIGEST, ReviewArgs, definition, digest
from caliburn.policy.review import ReviewDenied, ReviewPolicy
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import LostLease, get_store
from caliburn.sandbox.contracts import WORKSPACE_DIGEST, Operation, definitions
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue
from caliburn.tool_factory.checks import CheckQueue
from caliburn.tool_factory.contracts import FACTORY_DIGEST, INPUTS, CheckArgs
from caliburn.tool_factory.contracts import definitions as factory_definitions
from caliburn.tool_factory.execution_contracts import EXEC_DIGEST, ExecuteArgs, ExecutionReviewArgs
from caliburn.tool_factory.execution_contracts import definitions as execution_definitions
from caliburn.tool_factory.execution_queue import ExecutionQueue
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.release_contracts import ReleaseDenied
from caliburn.tool_factory.release_queue import InvocationQueue
from caliburn.tool_factory.release_service import ReleaseService
from caliburn.tool_factory.service import Factory, FactoryDenied
from caliburn.tools import CURATED_DIGEST, ToolError, execute_curated_tool, tool_definitions


class ProtocolError(Exception):
    pass


def normalize(response):
    try:
        msg = response["choices"][0]["message"]
        if not isinstance(msg, dict):
            raise TypeError()
        calls = msg.get("tool_calls") or []
        if not isinstance(calls, list) or len(calls) > 8:
            raise ValueError()
        result = {"role": "assistant", "content": msg.get("content")}
        if result["content"] is not None and not isinstance(result["content"], str):
            raise ValueError()
        if calls:
            clean, seen = [], set()
            for call in calls:
                cid, name, args = (
                    call["id"],
                    call["function"]["name"],
                    call["function"]["arguments"],
                )
                if not all(isinstance(v, str) and v for v in (cid, name, args)):
                    raise ValueError()
                if cid in seen or len(cid) > 200 or len(args) > 16384:
                    raise ValueError()
                seen.add(cid)
                clean.append(
                    {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
                )
            result["tool_calls"] = clean
        if len(json.dumps(result).encode()) > 100000:
            raise ValueError()
        return result
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProtocolError() from exc


def next_call(messages):
    index = len(messages) - 1
    done = set()
    while index >= 0 and messages[index]["role"] == "tool":
        done.add(messages[index]["tool_call_id"])
        index -= 1
    if index >= 0 and messages[index]["role"] == "assistant":
        for call in messages[index].get("tool_calls", []):
            if call["id"] not in done:
                return call
    return None


class Worker:
    def __init__(
        self,
        store,
        model,
        *,
        name=None,
        lease_seconds=15,
        output_tokens=1024,
        call_cost=0.0,
        secrets=(),
    ):
        self.store, self.model = store, model
        self.secrets = secrets
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.output_tokens, self.call_cost = output_tokens, call_cost

    async def _db(self, method, *args):
        return await asyncio.to_thread(method, *args)

    async def _watch(self, task_id, token, execution):
        while True:
            await asyncio.sleep(min(self.lease_seconds / 3, 0.25))
            try:
                alive = await self._db(self.store.heartbeat, task_id, token, self.lease_seconds)
            except LostLease:
                alive = False
            if not alive:
                execution.cancel()
                return

    async def run_once(self):
        task = await self._db(self.store.claim, self.name, self.lease_seconds)
        if task is None:
            return False
        execution = asyncio.create_task(self._execute(task))
        watch = asyncio.create_task(self._watch(task["id"], task["lease_token"], execution))
        try:
            await execution
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
        finally:
            watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch
        return True

    async def _execute(self, initial):
        tid, token = initial["id"], initial["lease_token"]
        try:
            while True:
                task = await self._db(self.store.get, tid, initial["actor"], initial["tenant"])
                if task["state"] != "RUNNING" or task["lease_token"] != token:
                    return
                if task["policy"].get("tool_digest") != CURATED_DIGEST:
                    await self._db(self.store.fail, tid, token, "tool_revision_changed")
                    return
                if (
                    task.get("workspace_ref")
                    and task["policy"].get("workspace_tools_digest") != WORKSPACE_DIGEST
                ):
                    await self._db(self.store.fail, tid, token, "workspace_tool_revision_changed")
                    return
                tools = tool_definitions()
                for name in task["policy"].get("capabilities", {}):

                    def authorize_capability(current_name=name, current_task=task):
                        with self.store.engine.connect() as c:
                            return (
                                ReleaseService(self.store)
                                .authorize(c, current_task, current_name)[1]
                                .manifest
                            )

                    manifest = await self._db(authorize_capability)
                    tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": name,
                                "description": manifest["description"],
                                "parameters": manifest["input_schema"],
                            },
                        }
                    )
                if "capability_request_execution" in task["policy"]["tools"]:
                    if task["policy"].get("exec_digest") != EXEC_DIGEST:
                        await self._db(
                            self.store.fail, tid, token, "factory_execution_revision_changed"
                        )
                        return
                    tools += execution_definitions()
                if any(name in task["policy"]["tools"] for name in INPUTS):
                    if task["policy"].get("factory_digest") != FACTORY_DIGEST:
                        await self._db(self.store.fail, tid, token, "factory_revision_changed")
                        return
                    tools += [
                        tool
                        for tool in factory_definitions()
                        if tool["function"]["name"] in task["policy"]["tools"]
                    ]
                if task.get("workspace_ref"):
                    tools += [
                        tool
                        for tool in definitions()
                        if tool["function"]["name"] in task["policy"]["tools"]
                    ]
                if "repo_request_review" in task["policy"]["tools"]:
                    if task["policy"].get("review_tool_digest") != REVIEW_TOOL_DIGEST:
                        await self._db(self.store.fail, tid, token, "review_tool_revision_changed")
                        return
                    tools.append(definition())
                messages = task["messages"]
                if contains_secret(messages, self.secrets):
                    await self._db(self.store.fail, tid, token, "platform_secret_denied")
                    return
                call = next_call(messages)
                review_result = None
                if call and call["function"]["name"] == "capability_request_execution":
                    if call["function"]["name"] not in task["policy"]["tools"]:
                        await self._db(self.store.fail, tid, token, "tool_policy_denied")
                        return
                    review_result = await self._db(
                        Qualification(self.store).ensure,
                        tid,
                        token,
                        ExecutionReviewArgs.model_validate_json(call["function"]["arguments"]),
                        digest({"messages": len(messages), "call": call}),
                    )
                    if review_result is None:
                        return
                if call and call["function"]["name"] == "repo_request_review":
                    if call["function"]["name"] not in task["policy"]["tools"]:
                        await self._db(self.store.fail, tid, token, "tool_policy_denied")
                        return
                    args = ReviewArgs.model_validate_json(call["function"]["arguments"])
                    review_result = await self._db(
                        ReviewPolicy(self.store).ensure,
                        tid,
                        token,
                        args,
                        digest({"messages": len(messages), "call": call}),
                    )
                    if review_result is None:
                        return
                kind = "TOOL" if call else "MODEL"
                reserve = (
                    0
                    if call
                    else (
                        len(json.dumps([messages, tools], ensure_ascii=True).encode())
                        + 1024
                        + self.output_tokens
                    )
                )
                step = await self._db(
                    self.store.prepare,
                    tid,
                    token,
                    kind,
                    call or {},
                    reserve,
                    0 if call else self.call_cost,
                )
                if step is None:
                    return
                timeout = min(
                    task["limits"]["call_timeout_seconds"],
                    max(0.001, task["deadline"] - await self._db(self._now)),
                )
                async with asyncio.timeout(timeout):
                    if call:
                        name = call["function"]["name"]
                        if name not in task["policy"]["tools"]:
                            await self._db(self.store.fail, tid, token, "tool_policy_denied")
                            return
                        try:
                            if (
                                name == "repo_request_review"
                                or name == "capability_request_execution"
                            ):
                                result = review_result
                            elif name in task["policy"].get("capabilities", {}):
                                result = await InvocationQueue(self.store).invoke(
                                    tid, token, step["id"], name, call["function"]["arguments"]
                                )
                            elif name == "capability_execute_tests":
                                result = await ExecutionQueue(self.store).invoke(
                                    tid,
                                    token,
                                    step["id"],
                                    ExecuteArgs.model_validate_json(call["function"]["arguments"]),
                                )
                            elif name == "capability_check":
                                result = await CheckQueue(self.store).invoke(
                                    tid,
                                    token,
                                    step["id"],
                                    CheckArgs.model_validate_json(call["function"]["arguments"]),
                                )
                            elif name in INPUTS:
                                result = await self._db(
                                    Factory(self.store, self.secrets).invoke,
                                    tid,
                                    token,
                                    step["id"],
                                    name,
                                    call["function"]["arguments"],
                                )
                            elif name.startswith("repo_"):
                                operation = Operation(
                                    tool=name, arguments=json.loads(call["function"]["arguments"])
                                )
                                result = await WorkspaceQueue(self.store).invoke(
                                    tid, token, step["id"], operation
                                )
                            else:
                                result = execute_curated_tool(name, call["function"]["arguments"])
                        except (ToolError, ValueError):
                            result = {"ok": False, "error": "invalid_tool_arguments"}
                        if contains_secret(result, self.secrets):
                            await self._db(self.store.fail, tid, token, "platform_secret_denied")
                            return
                        message = {
                            "role": "tool",
                            "name": name,
                            "tool_call_id": call["id"],
                            "content": json.dumps(result),
                        }
                        final = False
                    else:
                        message = normalize(await self.model.complete(messages, tools))
                        if contains_secret(message, self.secrets):
                            await self._db(self.store.fail, tid, token, "platform_secret_denied")
                            return
                        if (
                            len(json.dumps(message, ensure_ascii=False).encode())
                            > self.output_tokens * 4
                        ):
                            raise ProtocolError()
                        final = not message.get("tool_calls")
                await self._db(self.store.commit, tid, token, step["id"], message, final)
                if final:
                    return
        except ReleaseDenied:
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "registry_policy_denied")
        except FactoryDenied:
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "factory_policy_denied")
        except ReviewDenied:
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "review_policy_denied")
        except WorkspaceDenied:
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "workspace_policy_denied")
        except LostLease:
            return
        except TimeoutError:
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "call_timeout", "TIMED_OUT")
        except ProtocolError:
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "model_protocol_error")
        except Exception:  # noqa: BLE001 -- sanitize the complete untrusted provider boundary
            # Never serialize provider exceptions, URLs or credential-bearing response bodies.
            with contextlib.suppress(LostLease):
                await self._db(self.store.fail, tid, token, "execution_failed")

    def _now(self):
        with self.store.engine.connect() as c:
            return self.store.now(c)

    async def serve(self):
        while True:
            try:
                if not await self.run_once():
                    await asyncio.sleep(0.25)
            except Exception:  # noqa: BLE001 -- reconnect after DB outage without leaking DSNs
                # DB unavailable: retain durable work, retry without printing secrets/DSN.
                await asyncio.sleep(1)


def main():
    settings = get_settings()
    asyncio.run(
        Worker(
            get_store(settings.database_url),
            create_model(settings),
            output_tokens=settings.max_output_tokens,
            call_cost=settings.model_call_cost,
            secrets=platform_secrets(settings),
        ).serve()
    )


if __name__ == "__main__":
    main()
