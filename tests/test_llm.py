"""No live upstream calls: transport tests verify no fallback and credential separation."""

import json
from dataclasses import replace

import httpx
import pytest

from caliburn.config import get_settings
from caliburn.llm import OpenAICompatibleModel, ProviderError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body", [(200, []), (200, {}), (503, {"error": "private-response"})]
)
async def test_upstream_failure_has_no_fallback_or_body_leak(monkeypatch, status, body):
    attempts = []

    async def handler(request):
        attempts.append(request)
        return httpx.Response(status, json=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    settings = replace(
        get_settings(),
        provider="openai_compatible",
        upstream_model="fixture-upstream",
        upstream_api_key="synthetic-transport-only",
        allow_commercial_fallback=False,
    )
    with pytest.raises(ProviderError) as exc:
        await OpenAICompatibleModel(settings).complete([{"role": "user", "content": "hello"}], [])
    assert len(attempts) == 1
    assert "private-response" not in str(exc.value)
    assert "synthetic-transport-only" not in attempts[0].content.decode()
    assert json.loads(attempts[0].content)["max_tokens"] == settings.max_output_tokens
    assert attempts[0].headers["Authorization"] == "Bearer synthetic-transport-only"


def test_nonfinite_limits_and_upstream_price_requirements(monkeypatch):
    from pydantic import ValidationError

    from caliburn.runtime.contracts import Submit

    for value in [float("nan"), float("inf")]:
        with pytest.raises(ValidationError):
            Submit(prompt="x", limits={"max_cost": value})
    monkeypatch.setenv("CALIBURN_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CALIBURN_MODEL_CALL_COST", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CALIBURN_MODEL_CALL_COST"):
        get_settings()


def test_explicit_api_file_aliases_and_secret_repr(monkeypatch, tmp_path):
    key = "synthetic-file-key-not-real"
    file = tmp_path / ".env.apikey"
    file.write_text('openai_api_key="' + key + '"\nopenai_model=gpt-6-luna\n', encoding="utf-8")
    monkeypatch.setenv("CALIBURN_API_ENV_FILE", str(file))
    get_settings.cache_clear()
    cfg = get_settings()
    assert cfg.provider == "fixture"  # reading credentials does not grant network use
    assert cfg.upstream_api_key == key and cfg.upstream_model == "gpt-6-luna"
    assert cfg.upstream_base_url == "https://api.openai.com/v1" and key not in repr(cfg)
    monkeypatch.setenv("CALIBURN_UPSTREAM_MODEL", "explicit-override")
    get_settings.cache_clear()
    assert get_settings().upstream_model == "explicit-override"
    file.write_text("CALIBURN_ALLOW_FACTORY_EXECUTION=true\n", encoding="utf-8")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="redacted"):
        get_settings()


async def test_luna_transport_profile_and_credential_separation(monkeypatch):
    attempts = []

    async def handler(request):
        attempts.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "42"}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    cfg = replace(
        get_settings(),
        provider="openai_compatible",
        upstream_model="gpt-6-luna",
        upstream_base_url="https://api.openai.com/v1",
        upstream_api_key="synthetic-header-only",
    )
    await OpenAICompatibleModel(cfg).complete([{"role": "user", "content": "synthetic"}], [])
    body = json.loads(attempts[0].content)
    assert (
        body["reasoning_effort"] == "none"
        and body["max_completion_tokens"] == cfg.max_output_tokens
    )
    assert body["store"] is False and body["service_tier"] == "default" and "max_tokens" not in body
    assert "synthetic-header-only" not in attempts[0].content.decode()
