"""Public inert assets; all task data/control still requires authenticated APIs."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(include_in_schema=False)
ROOT = Path(__file__).with_name("assets")
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
}


@router.get("/tasks/ui")
def console():
    return FileResponse(ROOT / "timeline.html", media_type="text/html", headers=HEADERS)


@router.get("/tasks/assets/{asset}")
def asset_file(asset: str):
    types = {
        "timeline.css": "text/css",
        "timeline.mjs": "text/javascript",
        "stream.mjs": "text/javascript",
    }
    if asset not in types:
        raise HTTPException(404, "Asset not found")
    return FileResponse(ROOT / asset, media_type=types[asset], headers=HEADERS)
