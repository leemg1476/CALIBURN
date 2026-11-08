"""Fixed container-only Git data runner; source text is never imported/executed."""

import hashlib
import json
import re
import signal
import subprocess
import sys
from pathlib import Path
from runpy import run_path


def main():
    signal.alarm(25)
    helpers = run_path("/opt/runner.py")
    workspace = run_path("/opt/git_workspace.py")
    try:
        raw = sys.stdin.buffer.read(5000001)
        if len(raw) > 5000000:
            raise ValueError()
        request = json.loads(raw)
        if set(request) != {"base", "candidate", "baseline_sha256", "candidate_sha256", "task_ref"}:
            raise ValueError()
        if not re.fullmatch("[a-f0-9-]{36}", request["task_ref"]):
            raise ValueError()
        for key, sha in (("base", "baseline_sha256"), ("candidate", "candidate_sha256")):
            result = helpers["run"](
                {
                    "files": request[key],
                    "digest": request[sha],
                    "operation": {"tool": "repo_list", "arguments": {}},
                }
            )
            if not result["ok"]:
                raise ValueError()
        directory = Path("/work/task")
        directory.mkdir()
        data, patch = workspace["build_workspace"](
            directory, request["base"], request["candidate"], request["task_ref"], timeout=18
        )
        data.update(
            baseline_sha256=request["baseline_sha256"],
            candidate_sha256=request["candidate_sha256"],
            diff=patch[:16384].decode("utf-8", errors="replace"),
            diff_sha256=hashlib.sha256(patch).hexdigest(),
            diff_truncated=len(patch) > 16384,
            mode="scoped_snapshot_reconstruction",
            source_executed=False,
        )
        isolation = helpers["isolation"]()
        isolation["runner_sha256"] = hashlib.sha256(
            b"".join(
                Path("/opt", name).read_bytes()
                for name in ("git_runner.py", "git_workspace.py", "runner.py")
            )
        ).hexdigest()
        output = {"ok": True, "data": data, "isolation": isolation}
        if len(json.dumps(output, ensure_ascii=True).encode()) > 131072:
            raise ValueError()
    except (ValueError, TypeError, KeyError, OSError, TimeoutError, subprocess.SubprocessError):
        output = {"ok": False, "error": "git_workspace_denied_or_failed"}
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
