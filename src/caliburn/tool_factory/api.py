"""Authenticated read-only candidate inspection; no activation or execution route."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from caliburn.config import Settings
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import NotFound, get_store
from caliburn.tool_factory.artifact_integrity import ArtifactDenied
from caliburn.tool_factory.checks import CheckQueue
from caliburn.tool_factory.registry import ArtifactRegistry
from caliburn.tool_factory.service import Factory, FactoryDenied


def router(auth):
    api = APIRouter(prefix="/api/v1/capabilities", tags=["quarantined capabilities"])

    @api.get("/artifacts/{artifact_id}")
    def artifact(
        artifact_id: str, response: Response, settings: Annotated[Settings, Depends(auth)]
    ):
        response.headers["Cache-Control"] = "no-store"
        try:
            data = ArtifactRegistry(
                get_store(settings.database_url), secrets=platform_secrets(settings)
            ).read(artifact_id)
            if contains_secret(data, platform_secrets(settings)):
                raise ArtifactDenied()
            return data
        except NotFound as exc:
            raise HTTPException(404, "Artifact not found") from exc
        except (ArtifactDenied, ValueError) as exc:
            raise HTTPException(409, "Artifact integrity/trust unavailable") from exc

    @api.get("/reports/{report_id}")
    def report(report_id: str, settings: Annotated[Settings, Depends(auth)]):
        try:
            result = CheckQueue(get_store(settings.database_url)).read(report_id)
            if contains_secret(result, platform_secrets(settings)):
                raise FactoryDenied()
            return result
        except NotFound as exc:
            raise HTTPException(404, "Report not found") from exc
        except FactoryDenied as exc:
            raise HTTPException(502, "Invalid report") from exc

    @api.get("/{bundle_id}")
    def read(bundle_id: str, settings: Annotated[Settings, Depends(auth)]):
        try:
            return Factory(get_store(settings.database_url), platform_secrets(settings)).read(
                bundle_id
            )
        except NotFound as exc:
            raise HTTPException(404, "Candidate not found") from exc
        except FactoryDenied as exc:
            raise HTTPException(502, "Forbidden credential material") from exc

    return api
