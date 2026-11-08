"""Model adapters. Provider fallback and data residency are policy-driven future work."""

import json
import re
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from caliburn.config import Settings


class ProviderError(Exception):
    pass


class ChatModel(Protocol):
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class FixtureModel:
    """Deterministic local fixture; never intended to be a useful LLM."""

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        last = messages[-1]
        if last["role"] == "tool":
            message = {"role": "assistant", "content": f"검증된 도구 결과: {last['content']}"}
        else:
            content = str(last.get("content", ""))
            match = re.search(r"(?:계산|sum)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", content)
            if match:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "fixture-call-1",
                            "type": "function",
                            "function": {
                                "name": "add_numbers",
                                "arguments": json.dumps(
                                    {"a": float(match[1]), "b": float(match[2])}
                                ),
                            },
                        }
                    ],
                }
            else:
                message = {
                    "role": "assistant",
                    "content": "CALIBURN 테스트 모델 연결 성공. 실제 추론에는 LLM 설정이 필요합니다.",
                }
        return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


class OpenAICompatibleModel:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        endpoint = self.config.upstream_base_url.rstrip("/") + "/chat/completions"
        headers: dict[str, str] = {}
        if self.config.upstream_api_key:
            headers["Authorization"] = f"Bearer {self.config.upstream_api_key}"
        body = {
            "model": self.config.upstream_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }
        if urlsplit(self.config.upstream_base_url).hostname == "api.openai.com":
            body.update(
                max_completion_tokens=self.config.max_output_tokens,
                store=False,
                service_tier="default",
            )
            if self.config.upstream_model == "gpt-6-luna":
                body["reasoning_effort"] = "none"
        else:
            body["max_tokens"] = self.config.max_output_tokens
        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=False) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict) or not result.get("choices"):
                    raise ProviderError("Upstream response lacks choices")
                return result
        except (httpx.HTTPError, ValueError) as exc:
            # Do not leak upstream response bodies or token-bearing URLs.
            raise ProviderError("Upstream LLM request failed") from exc


def create_model(config: Settings) -> ChatModel:
    if config.provider == "fixture":
        return FixtureModel()
    return OpenAICompatibleModel(config)
