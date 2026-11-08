"""Source remains data here; actual repair execution is covered separately."""

import hashlib
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, insert, select
from sqlalchemy.exc import DBAPIError

from caliburn.policy.schema import candidates
from caliburn.runtime.contracts import Submit
from caliburn.sandbox.contracts import Bundle, Operation, Result
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue
from caliburn.sandbox.runner import run


def task_fixture(durable):
    queue = WorkspaceQueue(durable)
    wid = queue.register(
        Bundle(files={"calc.py": "old\n", "README.md": "original\n"}), propose_patch=True
    )
    task = durable.submit(
        Submit(prompt="bounded inert ancestry", workspace_ref=wid, limits={"max_tool_calls": 40})
    )
    lease = durable.claim("ancestry-fixture", 120)
    return queue, wid, task, lease["lease_token"]


def patch(durable, queue, task, token, path, old, new, parent=None):
    operation = Operation(
        tool="repo_patch",
        arguments={
            "path": path,
            "expected_sha256": hashlib.sha256(old.encode()).hexdigest(),
            "old": old,
            "new": new,
            "parent_candidate_ref": parent,
        },
    )
    step = durable.prepare(task["id"], token, "TOOL", operation.model_dump())
    queue.request(task["id"], token, step["id"], operation)
    job = queue.claim("sha256:" + "a" * 64)
    result = Result.model_validate(
        run({"files": job["files"], "digest": job["digest"], "operation": job["operation"]})
    )
    queue.finish(job, result)
    result = queue.poll(task["id"], token, job["id"])
    durable.commit(
        task["id"],
        token,
        step["id"],
        {
            "role": "tool",
            "name": "repo_patch",
            "tool_call_id": step["id"],
            "content": json.dumps(result.model_dump()),
        },
    )
    return result.candidate_ref


def test_parent_patch_preserves_other_files_and_cross_task_is_denied(durable):
    queue, wid, task, token = task_fixture(durable)
    root = patch(durable, queue, task, token, "calc.py", "old\n", "fixed\n")
    child = patch(durable, queue, task, token, "README.md", "original\n", "updated\n", root)
    with durable.engine.connect() as c:
        row = c.execute(select(candidates).where(candidates.c.id == child)).mappings().one()
        assert row["parent_id"] == root
        assert row["files"] == {"calc.py": "fixed\n", "README.md": "updated\n"}
    other = durable.submit(Submit(prompt="foreign candidate", workspace_ref=wid))
    other_lease = durable.claim("foreign-parent-fixture", 30)
    assert other_lease["id"] == other["id"]
    with pytest.raises(WorkspaceDenied):
        patch(
            durable, queue, other, other_lease["lease_token"], "calc.py", "fixed\n", "bad\n", root
        )
    if durable.engine.dialect.name == "postgresql":
        # Bypassing the queue cannot insert a parent from another task either.
        step = durable.prepare(other["id"], other_lease["lease_token"], "TOOL", {})
        with pytest.raises(DBAPIError), durable.engine.begin() as c:
            clone = dict(
                row, id=str(uuid4()), parent_id=root, task_id=other["id"], step_id=step["id"]
            )
            c.execute(insert(candidates).values(**clone))


def test_candidate_ancestry_is_bounded_and_wrong_parent_base_hash_fails(durable):
    queue, _, task, token = task_fixture(durable)
    parent = patch(durable, queue, task, token, "calc.py", "old\n", "v1\n")
    # Parent is selected, so a hash of the original file is stale and creates no child.
    assert patch(durable, queue, task, token, "calc.py", "old\n", "wrong\n", parent) is None
    for revision in range(2, 33):
        parent = patch(
            durable, queue, task, token, "calc.py", f"v{revision - 1}\n", f"v{revision}\n", parent
        )
    with pytest.raises(WorkspaceDenied):
        patch(durable, queue, task, token, "calc.py", "v32\n", "v33\n", parent)
    with durable.engine.connect() as c:
        assert len(c.execute(select(candidates.c.id)).all()) == 32


def test_parent_migration_preserves_existing_root_candidate(durable):
    _queue, wid, task, token = task_fixture(durable)
    step = durable.prepare(task["id"], token, "TOOL", {})
    cid = str(uuid4())
    with durable.engine.begin() as c:
        cfg = Config("alembic.ini")
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0003_review")
        legacy = Table("policy_candidates", MetaData(), autoload_with=c)
        assert "parent_id" not in legacy.c
        source = Bundle(files={"calc.py": "old\n", "README.md": "original\n"})
        c.execute(
            insert(legacy).values(
                id=cid,
                task_id=task["id"],
                step_id=step["id"],
                workspace_id=wid,
                actor=task["actor"],
                tenant=task["tenant"],
                creator_role="legacy-fixture",
                base_digest=source.digest(),
                artifact_digest=source.digest(),
                files=source.files,
                patch={},
                created_at=durable.now(c),
            )
        )
        command.upgrade(cfg, "head")
        row = c.execute(select(candidates).where(candidates.c.id == cid)).mappings().one()
        assert row["parent_id"] is None and row["files"] == source.files
