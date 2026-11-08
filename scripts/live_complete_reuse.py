"""Opted-in paid qualification and cross-task reuse of the reviewed real candidate."""

import argparse
import ast
import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from live_llm_smoke import BudgetedModel
from sqlalchemy import select, text

from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.registry import ArtifactRegistry
from caliburn.tool_factory.release_service import ReleaseService
from caliburn.tool_factory.schema import exec_jobs, release_invocations


async def run(args):
    root = Path(args.root).resolve()
    out = root / ".caliburn/live-demo"
    state = json.loads((out / "qualification-state.json").read_text())
    os.environ["CALIBURN_API_ENV_FILE"] = str(root / ".env.apikey")
    os.environ["CALIBURN_PROVIDER"] = "openai_compatible"
    os.environ["CALIBURN_MODEL_CALL_COST"] = "0.01"
    get_settings.cache_clear()
    cfg = replace(get_settings(), max_output_tokens=768)
    store = Store(cfg.database_url)
    schema = state["schema"]
    with store.engine.begin() as c:
        if c.scalar(text("SELECT current_schema()")) != schema:
            raise ValueError("Wrong disposable schema")
        # Refresh only the two locally hardened trigger bodies; retain all real records.
        tree = ast.parse(Path("migrations/versions/0009_internal_registry.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = node.value
                for name in ("registry_version_guard", "registry_invocation_guard"):
                    if sql.startswith("CREATE FUNCTION " + name + "("):
                        c.execute(
                            text(sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
                        )
                        c.exec_driver_sql(
                            f'ALTER FUNCTION {name}() SET search_path = "{schema}", pg_temp'
                        )

    def role_store(kind):
        return Store(
            store.engine.url.update_query_dict(
                {"options": f"-csearch_path={schema} -crole={state['roles'][kind]}"}
            ).render_as_string(hide_password=False)
        )

    ledger = BudgetedModel(cfg, root / ".caliburn/live-llm-budget.json")
    secrets = platform_secrets(cfg)

    def save(data):
        (out / "reuse-result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def consume(tid, table, kind, module):
        started = time.monotonic()
        worker = asyncio.create_task(
            Worker(store, ledger, output_tokens=768, call_cost=0.01, secrets=secrets).run_once()
        )
        async with asyncio.timeout(150):
            while True:
                with store.engine.connect() as c:
                    row = c.execute(select(table).where(table.c.task_id == tid)).mappings().first()
                if row:
                    break
                if worker.done():
                    await worker
                    raise ValueError("Model did not request actual execution: " + tid)
                await asyncio.sleep(0.1)
        env = dict(
            os.environ,
            CALIBURN_PROVIDER="fixture",
            CALIBURN_DATABASE_URL=role_store(kind).engine.url.render_as_string(hide_password=False),
        )
        for key in ("CALIBURN_API_ENV_FILE", "CALIBURN_UPSTREAM_API_KEY", "OPENAI_API_KEY"):
            env.pop(key, None)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            module,
            "--image",
            state["image"],
            "--once",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, _stderr = await asyncio.wait_for(process.communicate(), 90)
        if process.returncode:
            worker.cancel()
            raise ValueError("Isolated executor failed")
        await asyncio.wait_for(worker, 90)
        final = store.get(tid)
        with store.engine.connect() as c:
            receipt = dict(c.execute(select(table).where(table.c.task_id == tid)).mappings().one())
        if final["state"] != "COMPLETED":
            raise ValueError("Task failed: " + tid + " " + str(final.get("error")))
        return {
            "task_id": tid,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "state": final["state"],
            "result": final["result"],
            "receipt": receipt,
            "model_calls": final["model_calls"],
            "tool_calls": final["tool_calls"],
        }

    reviewer_store = role_store("review")
    Qualification(reviewer_store).decide(
        state["review_request"], state["binding_sha256"], "APPROVE", ttl_seconds=3600
    )
    result = {
        "approval": "explicit user approval plus delegated development authority",
        "source_sha256": state["source_sha256"],
        "candidate": state["candidate_ref"],
        "scope": "internal_development",
        "real_model": cfg.upstream_model,
        "synthetic_business_data": True,
        "reuse": [],
    }
    result["qualification"] = await consume(
        state["qualification_task"], exec_jobs, "exec", "caliburn.tool_factory.execution_control"
    )
    save(result)
    print(
        json.dumps({"phase": "QUALIFICATION_PASSED", "task": state["qualification_task"]}),
        flush=True,
    )
    owner_artifacts = ArtifactRegistry(store)
    owner_artifacts.configure(state["roles"]["sign"], "local-demo-signer")
    private = Ed25519PrivateKey.generate()  # ephemeral trusted host only; never model input
    owner_artifacts.register_key(private.public_key().public_bytes_raw(), state["roles"]["sign"])
    signer_store = role_store("sign")
    aid = ArtifactRegistry(signer_store).publish(result["qualification"]["receipt"]["id"], private)
    owner = ReleaseService(store)
    owner.configure(state["roles"]["review"], "chat-operator-reviewer", "REVIEWER")
    owner.configure(state["roles"]["invoke"], "local-demo-invoker", "EXECUTOR")
    owner.configure(state["roles"]["sign"], "local-demo-signer", "SIGNER")
    request = owner.request(aid)
    ReleaseService(reviewer_store).decide(
        request, owner.inspect(request)["sha256"], "APPROVE", internal_license_approved=True
    )
    vid = ReleaseService(signer_store).activate(request, private)
    result.update(artifact_ref=aid, release_ref=vid)
    save(result)
    print(json.dumps({"phase": "REGISTERED", "release": vid}), flush=True)
    datasets = [
        [
            {"year": 2026, "month": 10, "region": "Seoul", "amount_cents": 12000},
            {"year": 2026, "month": 10, "region": "Seoul", "amount_cents": -2000},
            {"year": 2026, "month": 11, "region": "Busan", "amount_cents": 4500},
        ],
        [
            {"year": 2027, "month": 1, "region": "Jeju", "amount_cents": 800},
            {"year": 2027, "month": 1, "region": "Jeju", "amount_cents": 200},
            {"year": 2026, "month": 12, "region": "Daegu", "amount_cents": -50},
        ],
    ]
    for rows, expected in zip(datasets, (14500, 950), strict=True):
        task = store.submit(
            Submit(
                prompt="Use the registered monthly_region_sales tool to aggregate these sales records by year, month and region, accounting for refunds. Report the actual returned result. Records: "
                + json.dumps(rows),
                limits={
                    "max_steps": 4,
                    "max_tool_calls": 2,
                    "max_tokens": 15000,
                    "max_cost": 0.04,
                    "timeout_seconds": 300,
                    "call_timeout_seconds": 90,
                },
            ),
            allow_registry_invocation=True,
        )
        proof = await consume(
            task["id"], release_invocations, "invoke", "caliburn.tool_factory.release_control"
        )
        receipt = proof["receipt"]
        proof["expected_total_cents"] = expected
        proof["input_records"] = rows
        if receipt["release_id"] != vid or receipt["result"]["value"]["total_cents"] != expected:
            raise ValueError("Actual isolated reuse output mismatch")
        result["reuse"].append(proof)
        result["budget"] = ledger.state
        save(result)
        print(
            json.dumps({"phase": "REUSED", "task": task["id"], "expected_total_cents": expected}),
            flush=True,
        )
    result["metrics"] = owner.metrics()
    result["phase"] = "REAL_GENERATION_REPAIR_QUALIFICATION_AND_REUSE_PASSED"
    save(result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--allow-paid", action="store_true")
    a = p.parse_args()
    if not a.allow_paid:
        p.error("Explicit paid opt-in required")
    try:
        asyncio.run(run(a))
    except Exception:  # noqa: BLE001 -- keep credential/upstream diagnostics out of CLI logs
        p.exit(2, "Live continuation failed; inspect sanitized task/receipt/ledger evidence\n")


if __name__ == "__main__":
    main()
