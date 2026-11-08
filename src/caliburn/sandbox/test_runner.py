"""Fixed container-only driver for reviewed stdlib unittest bundles.

Never import this module to execute source on the host. Input is sent only after
control-plane review authorization; each invocation is a fresh networkless container.
"""

import hashlib
import json
import os
import resource
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from runpy import run_path

_helpers = run_path("/opt/runner.py")
digest, isolation, path_ok = (_helpers[key] for key in ("digest", "isolation", "path_ok"))


def bundle(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 128:
        raise ValueError()
    folded = set()
    total = 0
    for name, content in files.items():
        if not path_ok(name) or not isinstance(content, str) or "\x00" in content:
            raise ValueError()
        size = len(content.encode())
        total += size
        if size > 65536 or name.casefold() in folded:
            raise ValueError()
        folded.add(name.casefold())
    if total > 1048576:
        raise ValueError()
    if any(str(p) in files for name in files for p in Path(name).parents):
        raise ValueError()
    return files


def materialize(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main():
    signal.alarm(25)
    child = None
    try:
        raw = sys.stdin.buffer.read(5000001)
        if len(raw) > 5000000:
            raise ValueError()
        request = json.loads(raw)
        if set(request) != {"files", "source_sha256", "plan", "plan_sha256"}:
            raise ValueError()
        files, plan = bundle(request["files"]), bundle(request["plan"])
        if digest(files) != request["source_sha256"] or digest(plan) != request["plan_sha256"]:
            raise ValueError()
        if not any(Path(name).name.startswith("test_") and name.endswith(".py") for name in plan):
            raise ValueError()
        # Source and independently registered tests have distinct roots; no overwrites.
        materialize(Path("/work/src"), files)
        materialize(Path("/work/tests"), plan)
        evidence = isolation()
        evidence["runner_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
            + Path("/opt/runner.py").read_bytes()
            + Path("/opt/check.py").read_bytes()
        ).hexdigest()
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "/opt/check.py"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/work", "LANG": "C.UTF-8"},
            start_new_session=True,
        )
        output, truncated = bytearray(), False
        deadline = time.monotonic() + 10
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        timed_out = False
        while selector.get_map():
            if time.monotonic() >= deadline:
                timed_out = True
                os.killpg(child.pid, signal.SIGKILL)
                break
            for key, _ in selector.select(0.05):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                remaining = 16384 - len(output)
                output.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
                    os.killpg(child.pid, signal.SIGKILL)
                    break
            if truncated:
                break
        selector.close()
        child.wait(timeout=1)
        result = {
            "ok": True,
            "data": {
                "status": "TIMEOUT"
                if timed_out
                else "OUTPUT_LIMIT"
                if truncated
                else "PASSED"
                if child.returncode == 0
                else "FAILED",
                "exit_code": child.returncode,
                "output": output.decode("utf-8", errors="replace"),
                "truncated": truncated,
                "source_sha256": request["source_sha256"],
                "plan_sha256": request["plan_sha256"],
            },
            "isolation": evidence,
        }
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        result = {"ok": False, "error": "invalid_test_request_or_driver_failure"}
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
