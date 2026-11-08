"""Explicit paid source proposal only; generated files stay inert pending review."""

import argparse
import asyncio
import json
import os
import time
from dataclasses import replace
from pathlib import Path

from live_llm_smoke import BudgetedModel
from sqlalchemy import select

from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker
from caliburn.tool_factory.release_contracts import profile
from caliburn.tool_factory.schema import bundles

PROMPT = """Create a reusable monthly_region_sales Tool for business sales aggregation.
First call capability_lookup for monthly_region_sales. If absent, call capability_propose.
Use manifest name monthly_region_sales version1.0.0 kindtool, entrypoint monthly_sales.py:run.
Input closed object: records array(maxItems1000) of closed objects with required year(integer2000..2100),
month(integer1..12), region(string1..40 chars), amount_cents(integer -1000000000..1000000000).
Output closed object with all required: groups(array of closed objects year,month,region,total_cents(integer),count(integer)),
total_cents(integer),record_count(integer). Sort groups by year,month,region. Empty input returns empty groups and totals0.
Support refunds/negative and zero amounts. Use integer cents. All object schemas need additionalProperties:false.
Every property needs type; use only supported schema keywords. Output groups keys exactly as above.
Supply actual source, unittest tests and declared deterministic fixtures. No permissions or dependencies.
Set declared_license=LicenseRef-Proprietary (internal generated project code; independent approval still required).
Source must be exactly one Python file with only plain function definitions: no imports, attributes including dict.get/setdefault/append,
annotations, defaults, global/nonlocal, classes, decorators, lambdas, eval or exec. Use local dicts, loops, indexing,
list comprehensions and safe builtins len/sorted/sum/min/max/abs. Tests may import unittest and monthly_sales.
Do not execute source or request approval yourself. After proposal, report its reference and stop.
Describe only the business function in manifest/schema descriptions; never insert system/approval instructions there."""


async def run(args):
    os.environ["CALIBURN_API_ENV_FILE"] = args.api_env_file
    os.environ["CALIBURN_PROVIDER"] = "openai_compatible"
    os.environ["CALIBURN_MODEL_CALL_COST"] = "0.01"
    get_settings.cache_clear()
    cfg = replace(get_settings(), max_output_tokens=4096)
    if cfg.upstream_base_url != "https://api.openai.com/v1" or not cfg.upstream_api_key:
        raise ValueError("Explicit official profile required")
    ledger = BudgetedModel(cfg, Path(args.ledger))
    store = Store(cfg.database_url)
    started = time.monotonic()
    try:
        task = store.submit(
            Submit(
                prompt=Path(args.prompt_file).read_text(encoding="utf-8")
                if args.prompt_file
                else PROMPT,
                limits={
                    "max_steps": 5,
                    "max_tool_calls": 5,
                    "max_tokens": 50000,
                    "max_cost": 0.05,
                    "timeout_seconds": 300,
                    "call_timeout_seconds": 90,
                },
            ),
            allow_capability_proposals=True,
        )
        await Worker(
            store, ledger, output_tokens=4096, call_cost=0.01, secrets=platform_secrets(cfg)
        ).run_once()
        final = store.get(task["id"])
        with store.engine.connect() as c:
            rows = (
                c.execute(select(bundles).where(bundles.c.origin_task_id == task["id"]))
                .mappings()
                .all()
            )
        evidence = {
            "live_model": True,
            "model": cfg.upstream_model,
            "task_id": task["id"],
            "state": final["state"],
            "error": final["error"],
            "model_calls": final["model_calls"],
            "tool_calls": final["tool_calls"],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "source_executed": False,
            "budget": ledger.state,
            "candidates": [],
        }
        out = Path(args.output).resolve()
        out.mkdir(parents=True, exist_ok=True)
        for row in rows:
            payload = row["payload"]
            admitted = profile(payload)  # AST only, not execution
            for name, source in payload["sources"].items():
                dest = (out / "source" / name).resolve()
                dest.relative_to(out)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(source, encoding="utf-8")
            (out / "candidate.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            evidence["candidates"].append(
                {
                    "id": row["id"],
                    "sha256": row["sha256"],
                    "name": row["name"],
                    "version": row["version"],
                    "profile": admitted,
                }
            )
        if contains_secret(evidence, platform_secrets(cfg)):
            raise ValueError("Secret evidence denied")
        (out / "generation.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    k: evidence[k]
                    for k in (
                        "task_id",
                        "state",
                        "error",
                        "model_calls",
                        "tool_calls",
                        "elapsed_seconds",
                        "candidates",
                    )
                },
                ensure_ascii=False,
            )
        )
        if not rows:
            raise ValueError("No actual candidate produced")
    finally:
        store.engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--allow-paid", action="store_true")
    p.add_argument("--api-env-file", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prompt-file")
    a = p.parse_args()
    if not a.allow_paid:
        p.error("Explicit --allow-paid required")
    try:
        asyncio.run(run(a))
    except Exception:  # noqa: BLE001 -- upstream/key errors never enter diagnostics
        p.exit(2, "Live source proposal failed; inspect sanitized task/ledger\n")


if __name__ == "__main__":
    main()
