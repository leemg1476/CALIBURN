"""Curated demonstration tools; generated tools never execute here."""

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class ToolError(Exception):
    pass


class AddNumbersArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: float
    b: float


class UtcNowArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddNumbersResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sum: float


class UtcNowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utc: str


CURATED_DIGEST = sha256(Path(__file__).read_bytes()).hexdigest()
TOOL_CONTRACTS = {
    name: {
        "version": "1.0.0",
        "owner": "caliburn-maintainers",
        "sha256": CURATED_DIGEST,
        "permissions": [],
        "egress": [],
        "side_effects": "none",
        "timeout_seconds": 1,
        "failure_modes": ["invalid_arguments", "non_finite_result"],
        "output_schema": output.model_json_schema(),
    }
    for name, output in (("add_numbers", AddNumbersResult), ("utc_now", UtcNowResult))
}


def _add_numbers(args: AddNumbersArgs) -> dict[str, float]:
    result = args.a + args.b
    if not all(math.isfinite(n) for n in [args.a, args.b, result]):
        raise ToolError("Only finite numbers are supported")
    return {"sum": result}


def _utc_now(_: UtcNowArgs) -> dict[str, str]:
    return {"utc": datetime.now(UTC).isoformat()}


TOOLS: dict[str, tuple[type[BaseModel], Callable[..., dict[str, Any]]]] = {
    "add_numbers": (AddNumbersArgs, _add_numbers),
    "utc_now": (UtcNowArgs, _utc_now),
}


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "Add two numbers"
                if name == "add_numbers"
                else "Get current UTC time",
                "parameters": args_type.model_json_schema(),
            },
        }
        for name, (args_type, _) in TOOLS.items()
    ]


def execute_curated_tool(name: str, raw_args: str) -> dict[str, Any]:
    if name not in TOOLS:
        raise ToolError("Tool is not in the curated allowlist")
    if len(raw_args) > 16_384:
        raise ToolError("Tool arguments exceed limit")
    args_type, fn = TOOLS[name]
    try:
        arguments = json.loads(raw_args)
        validated = args_type.model_validate(arguments)
        result = fn(validated)
        output_type = AddNumbersResult if name == "add_numbers" else UtcNowResult
        return output_type.model_validate(result).model_dump()
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ToolError("Invalid tool arguments") from exc
