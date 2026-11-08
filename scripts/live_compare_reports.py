"""Paid real-model multi-step sales comparison using an existing internal release."""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from live_llm_smoke import BudgetedModel
from sqlalchemy import select

from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.schema import steps
from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker
from caliburn.tool_factory.schema import release_invocations


async def run(args):
    root = Path(args.root).resolve()
    state = json.loads((root / ".caliburn/live-demo/qualification-state.json").read_text())
    proof = json.loads(Path(args.proof).read_text())
    os.environ["CALIBURN_API_ENV_FILE"] = str(root / ".env.apikey")
    os.environ["CALIBURN_PROVIDER"] = "openai_compatible"
    os.environ["CALIBURN_MODEL_CALL_COST"] = "0.01"
    get_settings.cache_clear()
    cfg = replace(get_settings(), max_output_tokens=768)
    store = Store(cfg.database_url)
    budget = BudgetedModel(cfg, root / ".caliburn/live-llm-budget.json")
    env = dict(
        os.environ,
        CALIBURN_PROVIDER="fixture",
        CALIBURN_DATABASE_URL=store.engine.url.update_query_dict(
            {"options": f"-csearch_path={state['schema']} -crole={state['roles']['invoke']}"}
        ).render_as_string(hide_password=False),
    )
    for key in ("CALIBURN_API_ENV_FILE", "CALIBURN_UPSTREAM_API_KEY", "OPENAI_API_KEY"):
        env.pop(key, None)
    executor = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "caliburn.tool_factory.release_control",
        "--image",
        state["image"],
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        datasets = {
            name: item["input_records"]
            for name, item in zip(("A", "B"), proof["reuse"], strict=True)
        }
        task = (
            store.get(args.task_id)
            if args.task_id
            else store.submit(
                Submit(
                    prompt="Compare these two sales batches. First call monthly_region_sales separately for batch A and B. Then call add_numbers with the actual returned A total and negative B total to obtain A minus B. Never compute these stages without the tools. Finally report the two totals and the difference, noting refunds. Batches: "
                    + json.dumps(datasets),
                    limits={
                        "max_steps": 6,
                        "max_tool_calls": 4,
                        "max_tokens": 30000,
                        "max_cost": 0.06,
                        "timeout_seconds": 300,
                        "call_timeout_seconds": 90,
                    },
                ),
                allow_registry_invocation=True,
            )
        )
        if task["state"] != "COMPLETED":
            await asyncio.wait_for(
                Worker(
                    store, budget, output_tokens=768, call_cost=0.01, secrets=platform_secrets(cfg)
                ).run_once(),
                180,
            )
        final = store.get(task["id"])
        with store.engine.connect() as c:
            calls = [
                dict(x)
                for x in c.execute(
                    select(steps)
                    .where(steps.c.task_id == task["id"], steps.c.kind == "TOOL")
                    .order_by(steps.c.ordinal)
                ).mappings()
            ]
            receipts = [
                dict(x)
                for x in c.execute(
                    select(release_invocations)
                    .where(release_invocations.c.task_id == task["id"])
                    .order_by(release_invocations.c.created_at)
                ).mappings()
            ]
        assert final["state"] == "COMPLETED"
        assert len(receipts) == 2 and all(x["release_id"] == proof["release_ref"] for x in receipts)
        assert sorted(x["result"]["value"]["total_cents"] for x in receipts) == [950, 14500]
        addition = [x for x in calls if x["input"]["function"]["name"] == "add_numbers"]
        assert len(addition) == 1 and json.loads(addition[0]["output"]["content"])["sum"] == 13550
        evidence = {
            "task_id": task["id"],
            "state": final["state"],
            "real_model": cfg.upstream_model,
            "synthetic_business_data": True,
            "elapsed_seconds": round(final["updated_at"] - final["created_at"], 3),
            "elapsed_basis": "persisted database created_at to updated_at",
            "model_calls": final["model_calls"],
            "tool_calls": final["tool_calls"],
            "release_ref": proof["release_ref"],
            "result": final["result"],
            "observed_totals": [14500, 950],
            "observed_difference": 13550,
            "tools": [x["input"]["function"]["name"] for x in calls],
            "invocation_receipts": receipts,
            "cumulative_budget": budget.state,
        }
        Path(args.output).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    k: evidence[k]
                    for k in (
                        "task_id",
                        "state",
                        "elapsed_seconds",
                        "model_calls",
                        "tool_calls",
                        "observed_difference",
                    )
                }
            )
        )
    finally:
        executor.terminate()
        await asyncio.wait_for(executor.wait(), 15)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--proof", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--task-id", help="Export an already completed task without another paid call")
    p.add_argument("--allow-paid", action="store_true")
    a = p.parse_args()
    if not a.allow_paid:
        p.error("Explicit paid opt-in required")
    try:
        asyncio.run(run(a))
    except Exception:  # noqa: BLE001 -- never print upstream/credential diagnostics
        p.exit(2, "Live comparison failed; inspect sanitized task/ledger evidence\n")


if __name__ == "__main__":
    main()
