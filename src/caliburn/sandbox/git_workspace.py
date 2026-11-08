"""Fixed stdlib-only Git data workspace. No source execution or arbitrary commands."""

import os
import re
import subprocess
import time


class LocalGit:
    def __init__(self, repo, template, deadline):
        self.repo, self.deadline = repo, deadline
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"}
        }
        self.env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_ATTR_NOSYSTEM="1",
            GIT_NO_REPLACE_OBJECTS="1",
            GIT_NO_LAZY_FETCH="1",
            GIT_ALLOW_PROTOCOL="",
            GIT_AUTHOR_NAME="CALIBURN task snapshot",
            GIT_AUTHOR_EMAIL="snapshot@example.invalid",
            GIT_COMMITTER_NAME="CALIBURN task snapshot",
            GIT_COMMITTER_EMAIL="snapshot@example.invalid",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00+0000",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00+0000",
        )
        self.command = [
            "git",
            "--no-pager",
            "--no-replace-objects",
            "--literal-pathspecs",
            "-C",
            str(repo),
            "-c",
            "core.hooksPath=" + str(template),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.attributesFile=" + os.devnull,
            "-c",
            "credential.helper=",
            "-c",
            "protocol.allow=never",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.symlinks=false",
        ]

    def run(self, *args, data=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Checkout deadline")
        result = subprocess.run(
            [*self.command, *args],
            input=data,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=min(10, remaining),
            check=False,
        )
        if result.returncode or len(result.stdout) > 4000000:
            raise ValueError("Fixed local Git operation failed")
        return result.stdout

    def index(self, files):
        self.run("read-tree", "--empty")
        entries = []
        for name, content in sorted(files.items()):
            blob = self.run(
                "hash-object", "-w", "--no-filters", "--stdin", data=content.encode()
            ).strip()
            if not re.fullmatch(b"[a-f0-9]{40}", blob):
                raise ValueError("Unsupported Git object format")
            entries.append(b"100644 " + blob + b"\t" + name.encode() + b"\x00")
        self.run("update-index", "-z", "--index-info", data=b"".join(entries))
        return self.run("write-tree").decode().strip()


def build_workspace(directory, baseline, target, task_id, timeout=60):
    repo, template = directory / "repo", directory / "empty-template"
    repo.mkdir()
    template.mkdir()
    git = LocalGit(repo, template, time.monotonic() + timeout)
    version = git.run("--version").decode().strip()
    git.run("init", "--template=" + str(template))
    # Highest-precedence attributes disable transformations and custom diff drivers.
    info = repo / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "attributes").write_text(
        "* -filter -text -ident -working-tree-encoding diff\n", encoding="utf-8"
    )
    baseline_tree = git.index(baseline)
    commit = (
        git.run(
            "commit-tree",
            baseline_tree,
            data=("Scoped task baseline " + task_id + "\n").encode(),
        )
        .decode()
        .strip()
    )
    git.run("checkout", "--force", "--detach", commit)
    for name, content in baseline.items():
        if (repo / name).read_bytes() != content.encode():
            raise ValueError("Checkout transformed source")
    # Source is data only. No Git add/filter, source import, hooks or shell command.
    for name in baseline.keys() - target.keys():
        (repo / name).unlink()
    for name, content in target.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    candidate_tree = git.index(target)
    diff = git.run(
        "diff",
        "--cached",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--binary",
        "HEAD",
        "--",
    )
    names = git.run("diff", "--cached", "--name-only", "-z", "HEAD", "--")
    changed = [name.decode("utf-8") for name in names.split(b"\x00") if name]
    template.rmdir()
    return {
        "baseline_git_commit": commit,
        "baseline_tree": baseline_tree,
        "candidate_tree": candidate_tree,
        "git_version": version,
        "changed_files": changed,
    }, diff
