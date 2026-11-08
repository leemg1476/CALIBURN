"""Operator-only scoped task Git checkout/handoff. Never execute repository source.

Uses an existing operator Git binary; no Git dependency or host command privilege
is installed in API/worker/agent images. The baseline is reconstructed from the
authorized snapshot, not a clone of undisclosed original history.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from caliburn.config import get_settings
from caliburn.policy.review import ReviewDenied, candidate_source
from caliburn.policy.schema import candidates
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import NotFound, get_store
from caliburn.sandbox.contracts import Bundle
from caliburn.sandbox.git_workspace import LocalGit as LocalGit  # noqa: PLC0414 -- public compatibility
from caliburn.sandbox.git_workspace import build_workspace
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue


class CheckoutReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["task-git-checkout-v1"] = "task-git-checkout-v1"
    mode: Literal["scoped_snapshot_reconstruction"] = "scoped_snapshot_reconstruction"
    task_ref: str
    workspace_ref: str
    candidate_ref: str | None
    actor: str
    tenant: str
    original_commit: str | None
    baseline_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    candidate_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    baseline_git_commit: str = Field(pattern="^[a-f0-9]{40}$")
    baseline_tree: str = Field(pattern="^[a-f0-9]{40}$")
    candidate_tree: str = Field(pattern="^[a-f0-9]{40}$")
    diff_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    git_version: str
    source_executed: Literal[False] = False
    production_approved: Literal[False] = False


def load_source(store, task_id, candidate_id):
    with store.engine.begin() as c:
        task = store._row(c, task_id, "development-service", "development")
        workspace = WorkspaceQueue(store).workspace(c, task["workspace_ref"], task)
        if "read" not in workspace["permissions"]:
            raise WorkspaceDenied()
        baseline = Bundle(files=workspace["files"])
        target = baseline
        if candidate_id is not None:
            row = (
                c.execute(
                    select(candidates).where(
                        candidates.c.id == candidate_id,
                        candidates.c.task_id == task_id,
                        candidates.c.workspace_id == workspace["id"],
                        candidates.c.actor == task["actor"],
                        candidates.c.tenant == task["tenant"],
                    )
                )
                .mappings()
                .first()
            )
            if not row or row["base_digest"] != baseline.digest():
                raise WorkspaceDenied()
            candidate_source(c, task, workspace, row["parent_id"])
            target = Bundle(files=row["files"])
            if target.digest() != row["artifact_digest"]:
                raise WorkspaceDenied()
        origin = workspace["provenance"].get("commit")
        if not isinstance(origin, str) or not re.fullmatch("[a-f0-9]{40}|[a-f0-9]{64}", origin):
            origin = None
        return (
            {
                "task_ref": task_id,
                "workspace_ref": workspace["id"],
                "candidate_ref": candidate_id,
                "actor": task["actor"],
                "tenant": task["tenant"],
                "original_commit": origin,
                "baseline_sha256": baseline.digest(),
                "candidate_sha256": target.digest(),
            },
            baseline,
            target,
        )


def output_directory(root):
    root = Path(root).absolute()
    if not root.is_dir() or root.parent == root:
        raise ValueError("Explicit existing private output directory required")
    if any(path.is_symlink() or path.is_junction() for path in (root, *root.parents)):
        raise ValueError("Linked output directories denied")
    return root.resolve(strict=True)


def remove_partial(directory, root):
    """Only our verified fresh output; Git object files can be read-only on Windows."""
    resolved = directory.resolve(strict=True)
    if resolved.parent != root or not resolved.name.startswith("caliburn-task-"):
        raise ValueError("Cleanup target escaped authorized output directory")

    def retry_readonly(function, name, error):
        path = Path(name)
        if (
            not isinstance(error, PermissionError)
            or path.is_symlink()
            or path.is_junction()
            or not path.resolve(strict=True).is_relative_to(resolved)
        ):
            raise error
        path.chmod(0o700 if path.is_dir() else 0o600)
        function(path)

    shutil.rmtree(resolved, onexc=retry_readonly)


def materialize(store, task_id, candidate_id, root, *, secrets, timeout=60):
    """Fresh output only; authority is scoped server data, never repository instructions."""
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise ValueError("Invalid checkout deadline")
    root = output_directory(root)
    scope, baseline, target = load_source(store, task_id, candidate_id)
    if contains_secret([scope, baseline.files, target.files], secrets):
        raise ValueError("Platform credentials forbidden")
    directory = Path(tempfile.mkdtemp(prefix="caliburn-task-", dir=root))
    succeeded = False
    try:
        metadata, diff = build_workspace(directory, baseline.files, target.files, task_id, timeout)
        current, _, _ = load_source(store, task_id, candidate_id)
        if current != scope:
            raise WorkspaceDenied()
        if contains_secret(diff.decode("utf-8", errors="replace"), secrets):
            raise ValueError("Platform credentials forbidden")
        report = CheckoutReport(
            **scope,
            baseline_git_commit=metadata["baseline_git_commit"],
            baseline_tree=metadata["baseline_tree"],
            candidate_tree=metadata["candidate_tree"],
            diff_sha256=hashlib.sha256(diff).hexdigest(),
            git_version=metadata["git_version"],
        )
        (directory / "candidate.patch").write_bytes(diff)
        (directory / "manifest.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        succeeded = True
        return directory, report
    finally:
        if not succeeded:
            remove_partial(directory, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--candidate")
    parser.add_argument(
        "--output-root",
        required=True,
        help="Existing private operator directory; fresh subdirectory only",
    )
    args = parser.parse_args()
    settings = get_settings()
    directory, report = materialize(
        get_store(settings.database_url),
        args.task,
        args.candidate,
        args.output_root,
        secrets=platform_secrets(settings),
    )
    print(
        json.dumps(
            {"directory": str(directory), "manifest": report.model_dump()}, ensure_ascii=True
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        OSError,
        TimeoutError,
        subprocess.SubprocessError,
        SQLAlchemyError,
        WorkspaceDenied,
        ReviewDenied,
        NotFound,
    ):
        raise SystemExit(
            "Task checkout denied or unavailable; no source/credentials logged"
        ) from None
