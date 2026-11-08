"""Real operator Git checkout; no source execution or remote repository changes."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_candidate_ancestry import patch, task_fixture

from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import NotFound
from caliburn.sandbox.checkout import LocalGit, materialize
from caliburn.sandbox.contracts import Bundle
from caliburn.sandbox.git_source import git_snapshot
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue


def read_git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-pager", "-C", str(repo), *args], stderr=subprocess.DEVNULL
    )


def test_actual_task_checkout_and_staged_candidate_diff(durable, tmp_path):
    queue, _, task, token = task_fixture(durable)
    candidate = patch(durable, queue, task, token, "calc.py", "old\n", "fixed\n")
    directory, report = materialize(durable, task["id"], candidate, tmp_path, secrets=())
    repo = directory / "repo"
    assert (repo / "calc.py").read_bytes() == b"fixed\n"
    assert read_git(repo, "show", "HEAD:calc.py") == b"old\n"
    assert read_git(repo, "rev-parse", "HEAD").decode().strip() == report.baseline_git_commit
    assert read_git(repo, "write-tree").decode().strip() == report.candidate_tree
    diff = (directory / "candidate.patch").read_bytes()
    assert b"-old\n+fixed\n" in diff
    assert hashlib.sha256(diff).hexdigest() == report.diff_sha256
    assert report.source_executed is False and report.production_approved is False
    assert json.loads((directory / "manifest.json").read_text()) == report.model_dump()
    again, second = materialize(durable, task["id"], candidate, tmp_path, secrets=())
    assert again != directory and second == report  # Replay never overwrites a prior checkout.
    other = durable.submit(
        Submit(prompt="not candidate owner", workspace_ref=task["workspace_ref"])
    )
    with pytest.raises(WorkspaceDenied):
        materialize(durable, other["id"], candidate, tmp_path, secrets=())
    with pytest.raises(NotFound):
        materialize(durable, "0" * 36, candidate, tmp_path, secrets=())


def test_real_pinned_git_import_to_task_checkout_preserves_scope(durable, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    read_git(source, "init")
    (source / "calc.py").write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")
    (source / "outside-scope.txt").write_text("not granted", encoding="utf-8")
    read_git(source, "add", "--", "calc.py", "outside-scope.txt")
    read_git(
        source,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "pinned fixture",
    )
    commit = read_git(source, "rev-parse", "HEAD").decode().strip()
    bundle, provenance = git_snapshot(source, ["calc.py"], commit)
    (source / "calc.py").write_text("dirty source must remain", encoding="utf-8")
    queue = WorkspaceQueue(durable)
    wid = queue.register(bundle, provenance=provenance)
    task = durable.submit(Submit(prompt="checkout granted commit data", workspace_ref=wid))
    # Host credentials, global hooks/templates and injected Git config must not reach Git.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(source))
    monkeypatch.setenv("CALIBURN_UPSTREAM_API_KEY", "fixture-credential-not-forwarded")
    directory, report = materialize(
        durable, task["id"], None, tmp_path, secrets=("fixture-credential-not-forwarded",)
    )
    assert report.original_commit == commit
    assert report.baseline_git_commit != commit
    assert (directory / "repo" / "calc.py").read_text() == bundle.files["calc.py"]
    assert not (directory / "repo" / "outside-scope.txt").exists()
    assert (directory / "candidate.patch").read_bytes() == b""
    assert (source / "calc.py").read_text() == "dirty source must remain"
    assert read_git(source, "rev-parse", "HEAD").decode().strip() == commit


def test_repository_attributes_cannot_transform_or_execute_source(durable, tmp_path, monkeypatch):
    queue = WorkspaceQueue(durable)
    files = {
        "data.txt": "a\nb\n",
        ".gitattributes": "* text eol=crlf filter=poison working-tree-encoding=UTF-16 diff=poison\n",
    }
    wid = queue.register(Bundle(files=files))
    task = durable.submit(Submit(prompt="data checkout", workspace_ref=wid))
    sentinel = tmp_path / "hook-ran"
    global_config = tmp_path / "global.config"
    global_config.write_text(
        f'[core]\n hooksPath = {tmp_path.as_posix()}\n[filter "poison"]\n required = true\n smudge = command-that-must-not-run\n[diff "poison"]\n textconv = command-that-must-not-run\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    (tmp_path / "post-checkout").write_text(
        f'#!/bin/sh\ntouch "{sentinel.as_posix()}"\n', encoding="utf-8"
    )
    (tmp_path / "post-checkout").chmod(0o755)
    directory, _ = materialize(durable, task["id"], None, tmp_path, secrets=())
    assert (directory / "repo" / "data.txt").read_bytes() == b"a\nb\n"
    assert not sentinel.exists()


@pytest.mark.parametrize("failure", ["timeout", "revoke", "secret", "cancel"])
def test_checkout_failure_leaves_no_partial_package(durable, tmp_path, monkeypatch, failure):
    queue, wid, task, _ = task_fixture(durable)
    original = LocalGit.run

    def intercepted(self, *args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fixed-fixture-git", 0.01)
        if failure == "cancel" and args[0] == "diff":
            raise KeyboardInterrupt()
        result = original(self, *args, **kwargs)
        if failure == "revoke" and args[0] == "diff":
            queue.revoke(wid)
        return result

    monkeypatch.setattr(LocalGit, "run", intercepted)
    with pytest.raises((subprocess.TimeoutExpired, WorkspaceDenied, ValueError, KeyboardInterrupt)):
        materialize(
            durable, task["id"], None, tmp_path, secrets=("old",) if failure == "secret" else ()
        )
    assert not list(tmp_path.glob("caliburn-task-*"))


def test_operator_cli_exports_actual_task_with_sanitized_output(durable, tmp_path):
    _, _, task, _ = task_fixture(durable)
    env = dict(
        os.environ, CALIBURN_DATABASE_URL=durable.engine.url.render_as_string(hide_password=False)
    )
    command = [
        sys.executable,
        "-m",
        "caliburn.sandbox.checkout",
        "--task",
        task["id"],
        "--output-root",
        str(tmp_path),
    ]
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, "Checkout CLI failed (output withheld)"
    output = json.loads(result.stdout)
    assert output["manifest"]["task_ref"] == task["id"]
    assert Path(output["directory"]).is_dir()


def test_checkout_scope_and_output_root_fail_closed(durable, tmp_path):
    queue = WorkspaceQueue(durable)
    wid = queue.register(
        Bundle(files={"x.py": "inert\n"}), actor="another-principal", tenant="another-tenant"
    )
    foreign = durable.submit(
        Submit(prompt="foreign scope", workspace_ref=wid),
        actor="another-principal",
        tenant="another-tenant",
    )
    with pytest.raises(NotFound):
        materialize(durable, foreign["id"], None, tmp_path, secrets=())
    _, _, own, _ = task_fixture(durable)
    for root in (tmp_path / "missing", Path(tmp_path.anchor)):
        with pytest.raises(ValueError):
            materialize(durable, own["id"], None, root, secrets=())


def test_cli_rejects_known_fixture_credentials_without_logging_source(durable, tmp_path):
    queue = WorkspaceQueue(durable)
    wid = queue.register(Bundle(files={"x.py": "test-service-token-secret"}))
    task = durable.submit(Submit(prompt="fixture confidentiality boundary", workspace_ref=wid))
    env = dict(
        os.environ, CALIBURN_DATABASE_URL=durable.engine.url.render_as_string(hide_password=False)
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "caliburn.sandbox.checkout",
            "--task",
            task["id"],
            "--output-root",
            str(tmp_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "test-service-token-secret" not in result.stdout + result.stderr
    assert not list(tmp_path.glob("caliburn-task-*"))
