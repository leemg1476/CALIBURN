"""Small, bounded tool-calling loop; not yet the durable autonomous runtime."""

import json
from typing import Any

from caliburn.llm import ChatModel
from caliburn.runtime.redaction import contains_secret
from caliburn.tools import ToolError, execute_curated_tool, tool_definitions


class AgentStepLimitError(Exception):
    pass


class AgentProtocolError(Exception):
    pass


async def run_agent(
    model: ChatModel,
    messages: list[dict[str, Any]],
    max_steps: int,
    forbidden_values: tuple[str, ...] = (),
) -> tuple[str, int]:
    conversation = list(messages)
    for step in range(1, max_steps + 1):
        if contains_secret(conversation, forbidden_values):
            raise AgentProtocolError("Platform credentials are forbidden in model input")
        response = await model.complete(conversation, tool_definitions())
        try:
            assistant_message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentProtocolError("Invalid model response") from exc
        if not isinstance(assistant_message, dict):
            raise AgentProtocolError("Invalid assistant message")
        if contains_secret(assistant_message, forbidden_values):
            raise AgentProtocolError("Provider returned forbidden credential material")

        raw_calls = assistant_message.get("tool_calls") or []
        if not raw_calls:
            return str(assistant_message.get("content") or ""), step
        if not isinstance(raw_calls, list) or len(raw_calls) > 8:
            raise AgentProtocolError("Too many tool calls in one turn")
        conversation.append(assistant_message)
        for call in raw_calls:
            try:
                name = call["function"]["name"]
                arguments = call["function"]["arguments"]
                call_id = call["id"]
                if not all(isinstance(value, str) for value in (name, arguments, call_id)):
                    raise TypeError("Malformed call fields")
            except (KeyError, TypeError) as exc:
                raise AgentProtocolError("Malformed tool call") from exc
            try:
                observation = {"ok": True, "data": execute_curated_tool(name, arguments)}
            except ToolError as exc:
                observation = {"ok": False, "error": str(exc)}
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(observation, ensure_ascii=False),
                }
            )
    raise AgentStepLimitError("Task exceeded the configured model-step limit")
