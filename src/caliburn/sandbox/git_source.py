"""Trusted operator local Git object reader. No checkout hooks, filters or lazy fetch."""

import os
import re
import subprocess
from pathlib import Path

from caliburn.sandbox.contracts import Bundle, safe_path


def git_snapshot(root, names, commit):
    root = Path(root).resolve(strict=True)
    if root.parent == root or not root.is_dir():
        raise ValueError("Invalid repository root")
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", commit):
        raise ValueError("An immutable full commit hash is required")
    if not 1 <= len(names) <= 128:
        raise ValueError("Invalid file count")
    git_dir = root / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink() or git_dir.is_junction():
        raise ValueError("Only an ordinary local Git repository is supported")
    for relative in ("config", "objects", "objects/info", "objects/pack"):
        path = git_dir / relative
        if path.is_symlink() or path.is_junction():
            raise ValueError("Linked Git metadata is denied")
    if any(
        (git_dir / "objects/info" / name).exists() for name in ("alternates", "http-alternates")
    ):
        raise ValueError("Alternate object stores are denied")
    if any((git_dir / "objects/pack").glob("*.promisor")):
        raise ValueError("Promisor repositories are denied")
    # Do not inherit secret-bearing environment, helpers, config overrides or fetch behavior.
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"}
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_LITERAL_PATHSPECS="1",
    )
    command = [
        "git",
        "--no-pager",
        "--no-replace-objects",
        "--literal-pathspecs",
        "-C",
        str(root),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "credential.helper=",
        "-c",
        "core.hooksPath=" + os.devnull,
    ]

    def read(*args):
        result = subprocess.run(
            [*command, *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if result.returncode:
            raise ValueError("Local Git object read failed")
        return result.stdout

    keys = (
        read("config", "--local", "--no-includes", "--name-only", "--get-regexp", ".")
        .decode()
        .splitlines()
    )
    if any(
        key.casefold().startswith(("include.", "includeif.", "extensions.partialclone"))
        or key.casefold().endswith(".promisor")
        for key in keys
    ):
        raise ValueError("Included configuration and partial clones are denied")
    if read("cat-file", "-t", commit).strip() != b"commit":
        raise ValueError("Not a commit")
    files = {}
    blob_ids = {}
    total = 0
    for name in names:
        safe_path(name)
        listing = read("ls-tree", "-z", commit, "--", name)
        records = listing.split(b"\x00")
        if len(records) != 2 or not records[0]:
            raise ValueError("Not a regular tracked file")
        meta, tab, actual = records[0].partition(b"\t")
        mode, kind, blob = meta.split(b" ")
        if (
            not tab
            or actual.decode("utf-8") != name
            or mode not in {b"100644", b"100755"}
            or kind != b"blob"
        ):
            raise ValueError("Links, submodules and nonregular objects are denied")
        size = int(read("cat-file", "-s", blob.decode()).strip())
        if size > 65536 or total + size > 1048576:
            raise ValueError("Workspace file/bundle size exceeded")
        content = read("cat-file", "blob", blob.decode())
        if len(content) != size:
            raise ValueError("Git blob changed")
        total += size
        files[name] = content.decode("utf-8")
        blob_ids[name] = blob.decode()
    bundle = Bundle(files=files)
    return bundle, {
        "source": "operator-local-git-objects",
        "commit": commit,
        "blob_ids": blob_ids,
        "bundle_sha256": bundle.digest(),
    }
