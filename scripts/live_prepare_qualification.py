"""Prepare real generated capability review; never decides or executes source."""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from live_llm_smoke import BudgetedModel
from sqlalchemy import select, text

from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle
from caliburn.tool_factory.checks import VerifierAuthority
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.schema import check_jobs, check_reports, exec_requests

OWNER_TESTS = {
    "test_owner_sales.py": """import unittest
from monthly_sales import run
class OwnerSales(unittest.TestCase):
    def test_empty_independently(self):
        self.assertEqual(run(records=[]), {'groups':[], 'total_cents':0, 'record_count':0})
    def test_boundary_and_refund(self):
        rows=[{'year':2025,'month':12,'region':'Seoul','amount_cents':100},
              {'year':2026,'month':1,'region':'Busan','amount_cents':200},
              {'year':2026,'month':1,'region':'Busan','amount_cents':-50}]
        self.assertEqual(run(records=rows), {'groups':[
            {'year':2025,'month':12,'region':'Seoul','total_cents':100,'count':1},
            {'year':2026,'month':1,'region':'Busan','total_cents':150,'count':2}],
            'total_cents':250,'record_count':3})
"""
}
CASES = [
    {
        "name": "independent_refund",
        "input": {
            "records": [
                {"year": 2027, "month": 2, "region": "Gwangju", "amount_cents": 333},
                {"year": 2027, "month": 2, "region": "Gwangju", "amount_cents": -111},
            ]
        },
        "expected": {
            "groups": [
                {"year": 2027, "month": 2, "region": "Gwangju", "total_cents": 222, "count": 2}
            ],
            "total_cents": 222,
            "record_count": 2,
        },
    },
    {
        "name": "zero_and_upper_boundary",
        "input": {
            "records": [
                {"year": 2000, "month": 1, "region": "AAA", "amount_cents": 0},
                {"year": 2100, "month": 12, "region": "ZZZ", "amount_cents": 1000000000},
            ]
        },
        "expected": {
            "groups": [
                {"year": 2000, "month": 1, "region": "AAA", "total_cents": 0, "count": 1},
                {"year": 2100, "month": 12, "region": "ZZZ", "total_cents": 1000000000, "count": 1},
            ],
            "total_cents": 1000000000,
            "record_count": 2,
        },
    },
]


async def run(args):
    os.environ["CALIBURN_API_ENV_FILE"] = args.api_env_file
    os.environ["CALIBURN_PROVIDER"] = "openai_compatible"
    os.environ["CALIBURN_MODEL_CALL_COST"] = "0.01"
    get_settings.cache_clear()
    cfg = replace(get_settings(), max_output_tokens=512)
    store = Store(cfg.database_url)
    out = Path(args.output).resolve()
    data = json.loads(Path(args.generation).read_text(encoding="utf-8"))
    candidate = data["candidates"][0]
    rid = candidate["id"]
    ledger = BudgetedModel(cfg, Path(args.ledger))
    with store.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        if not schema.startswith("caliburn_live_"):
            raise ValueError("Disposable live schema required")
        suffix = uuid4().hex[:12]
        roles = {
            kind: "live_" + kind + "_" + suffix
            for kind in ("verify", "review", "exec", "sign", "invoke")
        }
        for name in roles.values():
            c.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    VerifierAuthority(store).configure(roles["verify"], "local-demo-static-verifier")
    Qualification(store).configure(roles["review"], "chat-operator-reviewer", "REVIEWER")
    Qualification(store).configure(roles["exec"], "local-demo-factory-executor", "EXECUTOR")

    def url(role_name):
        return store.engine.url.update_query_dict(
            {"options": f"-csearch_path={schema} -crole={role_name}"}
        ).render_as_string(hide_password=False)

    task = store.submit(
        Submit(
            prompt=f"Call capability_check for immutable candidate {rid}. Do not execute any source. Then report the static result.",
            limits={
                "max_steps": 4,
                "max_tool_calls": 3,
                "max_tokens": 20000,
                "max_cost": 0.04,
                "timeout_seconds": 300,
                "call_timeout_seconds": 90,
            },
        ),
        allow_capability_checks=True,
    )
    worker = asyncio.create_task(
        Worker(
            store, ledger, output_tokens=512, call_cost=0.01, secrets=platform_secrets(cfg)
        ).run_once()
    )
    async with asyncio.timeout(90):
        while True:
            with store.engine.connect() as c:
                found = c.execute(
                    select(check_jobs.c.id).where(check_jobs.c.task_id == task["id"])
                ).first()
            if found:
                break
            if worker.done():
                raise ValueError("No actual static tool call")
            await asyncio.sleep(0.1)
    env = dict(os.environ, CALIBURN_DATABASE_URL=url(roles["verify"]), CALIBURN_PROVIDER="fixture")
    for key in ("CALIBURN_API_ENV_FILE", "CALIBURN_UPSTREAM_API_KEY", "OPENAI_API_KEY"):
        env.pop(key, None)
    verifier = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "caliburn.tool_factory.verifier",
        "--once",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, _stderr = await asyncio.wait_for(verifier.communicate(), 30)
    if verifier.returncode:
        raise ValueError("Independent static verifier failed")
    await asyncio.wait_for(worker, 90)
    with store.engine.connect() as c:
        report = (
            c.execute(
                select(check_reports)
                .join(check_jobs, check_jobs.c.id == check_reports.c.job_id)
                .where(check_jobs.c.task_id == task["id"])
            )
            .mappings()
            .one()
        )
    if report["body"]["classification"] != "REVIEW_REQUIRED":
        raise ValueError("Actual candidate blocked")
    plan = Qualification(store).register_plan(
        rid,
        report["id"],
        Bundle(files=OWNER_TESTS),
        args.image,
        ttl_seconds=3600,
        oracle_cases=CASES,
    )
    request_task = store.submit(
        Submit(
            prompt=f"Qualify monthly_region_sales@1.0.1 using operator plan {plan}. First call capability_request_execution. Wait for independent approval, then call capability_execute_tests with the approved request. Report actual evidence; never approve yourself.",
            limits={
                "max_steps": 6,
                "max_tool_calls": 5,
                "max_tokens": 30000,
                "max_cost": 0.06,
                "timeout_seconds": 3600,
                "call_timeout_seconds": 90,
            },
        ),
        allow_factory_execution=True,
    )
    await Worker(
        store, ledger, output_tokens=512, call_cost=0.01, secrets=platform_secrets(cfg)
    ).run_once()
    final = store.get(request_task["id"])
    if final["state"] != "WAITING_APPROVAL":
        raise ValueError("No actual independent-review wait")
    with store.engine.connect() as c:
        request = (
            c.execute(select(exec_requests).where(exec_requests.c.task_id == request_task["id"]))
            .mappings()
            .one()
        )
    state = {
        "generation_task": data["task_id"],
        "candidate_ref": rid,
        "candidate_sha256": candidate["sha256"],
        "source_sha256": candidate["profile"]["source_sha256"],
        "static_task": task["id"],
        "static_report": report["id"],
        "static_classification": report["body"]["classification"],
        "qualification_task": request_task["id"],
        "review_request": request["id"],
        "binding_sha256": request["sha256"],
        "binding": request["binding"],
        "plan_ref": plan,
        "image": args.image,
        "schema": schema,
        "roles": roles,
        "source_executed": False,
        "reviewer_identity_assurance": "local control-plane role; explicit chat approval required; not OIDC",
        "budget": ledger.state,
        "phase": "WAITING_FOR_USER_REVIEW",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "owner-tests.json").write_text(json.dumps(OWNER_TESTS, indent=2), encoding="utf-8")
    (out / "oracle-cases.json").write_text(json.dumps(CASES, indent=2), encoding="utf-8")
    (out / "qualification-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: state[k]
                for k in (
                    "candidate_ref",
                    "source_sha256",
                    "qualification_task",
                    "review_request",
                    "binding_sha256",
                    "phase",
                )
            }
        )
    )
    store.engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("api-env-file", "ledger", "generation", "output", "image"):
        p.add_argument("--" + field, required=True)
    p.add_argument("--allow-paid", action="store_true")
    a = p.parse_args()
    if not a.allow_paid:
        p.error("Explicit paid opt-in required")
    try:
        asyncio.run(run(a))
    except Exception:  # noqa: BLE001 -- sanitize upstream credential-bearing diagnostics
        p.exit(2, "Live qualification preparation failed; inspect sanitized task/ledger\n")


if __name__ == "__main__":
    main()
