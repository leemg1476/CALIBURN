"""Bootstrap-only environment configuration; replace with validated policy at M1/M4."""

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit


def api_file(path):
    if not path:
        return {}
    aliases = {
        "openai_api_key": "CALIBURN_UPSTREAM_API_KEY",
        "openai_model": "CALIBURN_UPSTREAM_MODEL",
        "openai_base_url": "CALIBURN_UPSTREAM_BASE_URL",
        "caliburn_upstream_api_key": "CALIBURN_UPSTREAM_API_KEY",
        "caliburn_upstream_model": "CALIBURN_UPSTREAM_MODEL",
        "caliburn_upstream_base_url": "CALIBURN_UPSTREAM_BASE_URL",
    }
    try:
        with Path(path).open("rb") as f:
            raw = f.read(16385)
        if len(raw) > 16384:
            raise ValueError()
        values = {}
        for line in raw.decode("utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.removeprefix("export ").partition("=")
            canonical = aliases.get(name.strip().lower())
            if not separator or not canonical or canonical in values:
                raise ValueError()
            value = value.strip()
            if value[:1] in {'"', "'"}:
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError()
                value = value[1:-1]
            if "\x00" in value:
                raise ValueError()
            values[canonical] = value
        return values
    except (OSError, ValueError, UnicodeError):
        raise ValueError("Invalid API environment file (values redacted)") from None


@dataclass(frozen=True)
class Settings:
    api_token: str = field(repr=False)
    provider: str
    model: str
    upstream_model: str
    upstream_base_url: str
    upstream_api_key: str = field(repr=False)
    max_steps: int
    db_path: str
    allow_commercial_fallback: bool
    database_url: str = field(
        default="postgresql+psycopg://caliburn@127.0.0.1:5432/caliburn", repr=False
    )
    max_output_tokens: int = 1024
    model_call_cost: float = 0.0
    task_max_cost: float = 0.0
    allow_capability_proposals: bool = False
    allow_capability_checks: bool = False
    allow_factory_execution: bool = False


@lru_cache
def get_settings() -> Settings:
    # Explicit path only: fixture tests/default services never load a developer key.
    values = api_file(os.getenv("CALIBURN_API_ENV_FILE", ""))

    def provider_value(name, default):
        return os.environ.get(name, values.get(name, default))

    settings = Settings(
        api_token=os.getenv("CALIBURN_API_TOKEN", ""),
        provider=os.getenv("CALIBURN_PROVIDER", "fixture"),
        model=os.getenv("CALIBURN_MODEL", "caliburn-agent"),
        upstream_model=provider_value("CALIBURN_UPSTREAM_MODEL", "not-configured"),
        upstream_base_url=provider_value(
            "CALIBURN_UPSTREAM_BASE_URL",
            "https://api.openai.com/v1" if values else "http://127.0.0.1:8001/v1",
        ),
        upstream_api_key=provider_value("CALIBURN_UPSTREAM_API_KEY", ""),
        max_steps=int(os.getenv("CALIBURN_MAX_STEPS", "6")),
        db_path=os.getenv("CALIBURN_DB_PATH", "./.caliburn/data.sqlite3"),
        allow_commercial_fallback=os.getenv("CALIBURN_ALLOW_COMMERCIAL_FALLBACK", "false")
        .strip()
        .lower()
        == "true",
        database_url=os.getenv(
            "CALIBURN_DATABASE_URL", "postgresql+psycopg://caliburn@127.0.0.1:5432/caliburn"
        ),
        max_output_tokens=int(os.getenv("CALIBURN_MAX_OUTPUT_TOKENS", "1024")),
        model_call_cost=float(os.getenv("CALIBURN_MODEL_CALL_COST", "0")),
        task_max_cost=float(os.getenv("CALIBURN_TASK_MAX_COST", "0")),
        allow_factory_execution=os.getenv("CALIBURN_ALLOW_FACTORY_EXECUTION", "false")
        .strip()
        .lower()
        == "true",
        allow_capability_checks=os.getenv("CALIBURN_ALLOW_CAPABILITY_CHECKS", "false")
        .strip()
        .lower()
        == "true",
        allow_capability_proposals=os.getenv("CALIBURN_ALLOW_CAPABILITY_PROPOSALS", "false")
        .strip()
        .lower()
        == "true",
    )
    if settings.provider not in {"fixture", "openai_compatible"}:
        raise ValueError("Unsupported CALIBURN_PROVIDER")
    if not 1 <= settings.max_steps <= 40:
        raise ValueError("CALIBURN_MAX_STEPS must be between 1 and 40")
    if settings.provider == "openai_compatible":
        if not math.isfinite(settings.model_call_cost) or settings.model_call_cost <= 0:
            raise ValueError("Set a positive conservative CALIBURN_MODEL_CALL_COST")
        try:
            endpoint = urlsplit(settings.upstream_base_url)
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError()
            _port = endpoint.port
        except ValueError:
            raise ValueError("Invalid upstream URL (credentials/query forbidden)") from None
        if settings.upstream_model == "not-configured":
            raise ValueError("Set CALIBURN_UPSTREAM_MODEL for real LLM calls")
    if not 1 <= settings.max_output_tokens <= 32768:
        raise ValueError("CALIBURN_MAX_OUTPUT_TOKENS must be between 1 and 32768")
    if not math.isfinite(settings.task_max_cost) or not 0 <= settings.task_max_cost <= 100:
        raise ValueError("CALIBURN_TASK_MAX_COST must be between 0 and 100")
    if not math.isfinite(settings.model_call_cost) or settings.model_call_cost < 0:
        raise ValueError("CALIBURN_MODEL_CALL_COST must be finite and nonnegative")
    return settings
