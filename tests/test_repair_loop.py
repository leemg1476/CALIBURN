"""Real iterative execution evidence; inference and independent identities are fixtures."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from test_review import PATCH, SOURCE
from test_reviewed_execution import PLAN

from caliburn.policy.review import ReviewDenied
from caliburn.policy.schema import candidates
from caliburn.runtime.contracts import Submit
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle
from caliburn.sandbox.control import DockerExecutor, Supervisor
from caliburn.sandbox.queue import WorkspaceQueue
from caliburn.sandbox.schema import jobs
from caliburn.sandbox.test_control import ReviewedTestExecutor


class RepairModelFixture:
    def __init__(self, plan_ref):
        self.plan = plan_ref

    async def complete(self, messages, tools):
        observations = [
            (m["name"], json.loads(m["content"])) for m in messages if m["role"] == "tool"
        ]
        if not observations:
            name, args = "repo_patch", {**PATCH, "new": "a + b + 1"}
        else:
            previous, result = observations[-1]
            if previous == "repo_patch":
                name, args = (
                    "repo_request_review",
                    {"candidate_ref": result["candidate_ref"], "plan_ref": self.plan},
                )
            elif previous == "repo_request_review":
                name, args = "repo_test", {"request_ref": result["data"]["request_ref"]}
            else:
                assert previous == "repo_test" and result["ok"]
                evidence = result["data"]
                assert evidence["baseline"]["status"] == "FAILED"
                if evidence["candidate"]["status"] == "PASSED":
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": "Candidate repaired after actual failing test; new independent review and retest passed."
                                }
                            }
                        ]
                    }
                assert evidence["candidate"]["status"] == "FAILED"
                assert "6 != 5" in evidence["candidate"]["output"]
                parent = next(data for tool, data in reversed(observations) if tool == "repo_patch")
                name, args = (
                    "repo_patch",
                    {
                        "parent_candidate_ref": parent["candidate_ref"],
                        "path": "calc.py",
                        "expected_sha256": parent["data"]["candidate_sha256"],
                        "old": "a + b + 1",
                        "new": "a + b",
                    },
                )
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": f"repair-{len(observations)}",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                        ]
                    }
                }
            ]
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("second_decision", ["APPROVE", "REJECT", "budget"])
async def test_actual_failed_candidate_repaired_with_new_review(
    durable, authority, second_decision
):
    data_image, test_image = (
        os.getenv("CALIBURN_SANDBOX_TEST_IMAGE"),
        os.getenv("CALIBURN_REVIEWED_TEST_IMAGE"),
    )
    if not data_image or not test_image:
        pytest.skip("Both actual Docker images required")
    policy, reviewer, _ = authority
    queue = WorkspaceQueue(durable)
    wid = queue.register(
        Bundle(files={"calc.py": SOURCE}),
        propose_patch=True,
        request_review=True,
        execute_reviewed_tests=True,
    )
    plan = policy.register_plan(wid, PLAN, test_image)
    task = durable.submit(
        Submit(
            prompt="Use test evidence to repair the candidate; every changed hash needs new independent review.",
            workspace_ref=wid,
            limits={
                "max_steps": 12,
                "max_tool_calls": 4 if second_decision == "budget" else 12,
                "max_tokens": 200000,
                "call_timeout_seconds": 40,
                "timeout_seconds": 180,
            },
        )
    )
    serving = [
        asyncio.create_task(Supervisor(queue, executor).serve())
        for executor in (DockerExecutor(data_image), ReviewedTestExecutor(test_image))
    ]
    try:
        await asyncio.wait_for(Worker(durable, RepairModelFixture(plan)).run_once(), 40)
        first = policy.views(task["id"])[0]
        assert durable.get(task["id"])["state"] == "WAITING_APPROVAL"
        reviewer.decide(first["id"], first["binding_sha256"], "APPROVE")
        await asyncio.wait_for(Worker(durable, RepairModelFixture(plan)).run_once(), 60)
        checkpoint = durable.get(task["id"])
        assert checkpoint["state"] == "WAITING_APPROVAL", checkpoint["error"]
        second = next(view for view in policy.views(task["id"]) if view["id"] != first["id"])
        assert second["status"] == "PENDING" and second["source_executed"] is False
        assert second["binding"]["parent_candidate_ref"] == first["binding"]["candidate_ref"]
        assert second["binding"]["patch_source_sha256"] == first["binding"]["candidate_sha256"]
        assert second["binding"]["candidate_sha256"] != first["binding"]["candidate_sha256"]
        assert (checkpoint["model_calls"], checkpoint["tool_calls"]) == (5, 4)
        assert not await Worker(
            durable, RepairModelFixture(plan)
        ).run_once()  # Old approval cannot resume new candidate.
        with pytest.raises(ReviewDenied):
            reviewer.decide(second["id"], first["binding_sha256"], "APPROVE")
        reviewer.decide(
            second["id"],
            second["binding_sha256"],
            "REJECT" if second_decision == "REJECT" else "APPROVE",
        )
        if second_decision != "REJECT":
            await asyncio.wait_for(Worker(durable, RepairModelFixture(plan)).run_once(), 60)
    finally:
        for process in serving:
            process.cancel()
        await asyncio.gather(*serving, return_exceptions=True)
    final = durable.get(task["id"])
    with durable.engine.connect() as c:
        versions = (
            c.execute(select(candidates).where(candidates.c.task_id == task["id"])).mappings().all()
        )
        executions = [
            dict(row)
            for row in c.execute(
                select(jobs)
                .where(
                    jobs.c.task_id == task["id"],
                    jobs.c.operation["tool"].as_string() == "repo_test",
                )
                .order_by(jobs.c.created_at)
            ).mappings()
        ]
    assert len(versions) == 2
    assert executions[0]["result"]["data"]["candidate"]["status"] == "FAILED"
    if second_decision == "APPROVE":
        assert final["state"] == "COMPLETED", final["error"]
        assert (final["model_calls"], final["tool_calls"]) == (7, 6)
        assert len(executions) == 2
        assert executions[1]["result"]["data"]["candidate"]["status"] == "PASSED"
        if path := os.getenv("CALIBURN_REPAIR_EVIDENCE"):
            Path(path).write_text(
                json.dumps(
                    {
                        "fixtures": ["model inference", "reviewer identity", "source/test plan"],
                        "actual": [
                            "PostgreSQL",
                            "two independent role decisions",
                            "data/test containers",
                            "durable worker loop",
                        ],
                        "state": final["state"],
                        "model_calls": final["model_calls"],
                        "tool_calls": final["tool_calls"],
                        "first_review": first,
                        "second_review": second,
                        "executions": [
                            {"image_digest": row["image_digest"], "result": row["result"]}
                            for row in executions
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    else:
        assert final["state"] == "FAILED"
        assert final["error"] == (
            "review_rejected" if second_decision == "REJECT" else "tool_call_limit"
        )
        assert (final["model_calls"], final["tool_calls"]) == (5, 4)
        assert len(executions) == 1
    assert final["reserved_tokens"] >= checkpoint["reserved_tokens"] > 0
