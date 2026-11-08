"""Operator-only workspace import; explicit file list, no recursive host access."""

import argparse
import subprocess
from pathlib import Path

from caliburn.config import get_settings
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import get_store
from caliburn.sandbox.contracts import Bundle, safe_path
from caliburn.sandbox.git_source import git_snapshot
from caliburn.sandbox.queue import WorkspaceQueue


def snapshot(root, names):
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or root.parent == root:
        raise ValueError("Workspace root must be a repository directory")
    if not 1 <= len(names) <= 128:
        raise ValueError("Invalid file count")
    files = {}
    total = 0
    for name in names:
        safe_path(name)
        path = root / name
        for parent in [path, *path.parents]:
            if parent == root:
                break
            if parent.is_symlink() or parent.is_junction():
                raise ValueError("Links are not allowed")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("File outside workspace or not a regular file")
        if resolved.stat().st_size > 65536:
            raise ValueError("File too large")
        content = resolved.read_text(encoding="utf-8")
        total += len(content.encode())
        if total > 1048576:
            raise ValueError("Workspace too large")
        files[name] = content
    return Bundle(files=files)


def main():
    p = argparse.ArgumentParser(
        description="Operator grant for an explicit reviewed snapshot; never a model tool"
    )
    p.add_argument("--root", required=True)
    p.add_argument("--file", action="append", required=True, dest="files")
    p.add_argument("--propose-patch", action="store_true")
    p.add_argument("--request-review", action="store_true")
    p.add_argument(
        "--git-image",
        help="Separately approved immutable Git data image; explicit git_inspect grant",
    )
    p.add_argument(
        "--execute-reviewed-tests",
        action="store_true",
        help="Separate operator grant; never bypasses independent exact-hash review",
    )
    p.add_argument(
        "--git-commit", help="Full immutable local commit hash; read committed objects only"
    )
    args = p.parse_args()
    settings = get_settings()
    if args.git_commit:
        bundle, provenance = git_snapshot(args.root, args.files, args.git_commit)
    else:
        bundle = snapshot(args.root, args.files)
        provenance = {
            "source": "operator-explicit-files",
            "files": sorted(bundle.files),
            "bundle_sha256": bundle.digest(),
        }
    if contains_secret(bundle.files, platform_secrets(settings)):
        raise SystemExit("Workspace contains forbidden platform credentials")
    wid = WorkspaceQueue(get_store(settings.database_url)).register(
        bundle,
        propose_patch=args.propose_patch,
        request_review=args.request_review,
        execute_reviewed_tests=args.execute_reviewed_tests,
        git_image_digest=args.git_image,
        provenance=provenance,
    )
    print(wid)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError):
        # Validation errors may include untrusted file contents; never print them.
        raise SystemExit("Workspace import denied by source/contract policy") from None
