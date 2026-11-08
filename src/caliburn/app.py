"""CALIBURN API and replaceable OpenAI chat adapter."""

import hmac
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException

from caliburn.agent import AgentProtocolError, AgentStepLimitError, run_agent
from caliburn.chat_adapter import durable_completion
from caliburn.config import Settings, get_settings
from caliburn.contracts import ChatCompletionRequest
from caliburn.llm import ProviderError, create_model
from caliburn.runtime.api import router
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.tool_factory.api import router as factory_router
from caliburn.web.routes import router as web_router

app = FastAPI(title="CALIBURN bootstrap", version="0.1.0")


def require_service_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> Settings:
    if not settings.api_token or settings.api_token == "replace-with-long-random-secret":
        raise HTTPException(status_code=503, detail="Configure a secure CALIBURN_API_TOKEN")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, settings.api_token):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return settings


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/v1/models")
def list_models(settings: Annotated[Settings, Depends(require_service_token)]) -> dict:
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": 0, "owned_by": "caliburn"}
            for name in (settings.model, settings.model + "-durable")
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completion(
    request: ChatCompletionRequest,
    settings: Annotated[Settings, Depends(require_service_token)],
):
    if request.model not in {settings.model, settings.model + "-durable"}:
        raise HTTPException(status_code=404, detail="Unknown CALIBURN model")
    if request.stream and request.model == settings.model:
        raise HTTPException(status_code=501, detail="Streaming not implemented in M0")
    if contains_secret(request.messages, platform_secrets(settings)):
        raise HTTPException(422, "Platform credentials are forbidden in model input")
    allowed_roles = {"system", "developer", "user", "assistant", "tool"}
    if any(message.get("role") not in allowed_roles for message in request.messages):
        raise HTTPException(status_code=422, detail="Invalid conversation role")
    if request.model == settings.model + "-durable":
        return await durable_completion(request, settings)
    try:
        content, steps = await run_agent(
            create_model(settings), request.messages, settings.max_steps, platform_secrets(settings)
        )
        if contains_secret(content, platform_secrets(settings)):
            raise HTTPException(502, "Provider returned forbidden credential material")
    except AgentStepLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentProtocolError, ProviderError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(datetime.now(UTC).timestamp()),
        "model": settings.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": None,
        "caliburn": {"model_steps": steps, "mode": "bootstrap-nonstreaming"},
    }


app.include_router(router(require_service_token))
app.include_router(web_router)
app.include_router(factory_router(require_service_token))
