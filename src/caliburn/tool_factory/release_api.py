"""Authenticated scoped read catalog; activation/review remain operator-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from caliburn.config import Settings
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import get_store
from caliburn.tool_factory.release_service import ReleaseService


def router(auth):
    api = APIRouter(prefix="/api/v1/registry", tags=["internal registered tools"])
    Auth = Annotated[Settings, Depends(auth)]

    def read(settings, kind):
        service = ReleaseService(
            get_store(settings.database_url), secrets=platform_secrets(settings)
        )
        data = service.active() if kind == "active" else service.metrics()
        if contains_secret(data, platform_secrets(settings)):
            raise HTTPException(502, "Registry data unavailable")
        return data

    @api.get("")
    def active(response: Response, settings: Auth):
        response.headers["Cache-Control"] = "no-store"
        return {"scope": "internal_development", "tools": read(settings, "active")}

    @api.get("/metrics")
    def metrics(response: Response, settings: Auth):
        response.headers["Cache-Control"] = "no-store"
        return {"versions": read(settings, "metrics")}

    return api
