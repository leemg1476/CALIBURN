"""Fixed stdlib-only isolated runner. Never import or execute repository contents.

The duplicated wire validation is intentional: this image has no platform/dependency
credentials or platform packages. It accepts a bounded JSON bundle on stdin only.
"""

import difflib
import hashlib
import json
import os
import signal
import socket
import sys
from pathlib import Path, PurePosixPath

MAX_INPUT = 2097152
MAX_OUTPUT = 131072


def digest(files):
    return hashlib.sha256(
        json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


DENIED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".ssh",
    ".aws",
    ".kube",
    ".docker",
    ".caliburn",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
    "id_rsa",
    "id_ed25519",
}


def path_ok(name):
    if not isinstance(name, str):
        return False
    p = PurePosixPath(name)
    return (
        name
        and len(name) <= 240
        and str(p) == name
        and not p.is_absolute()
        and not any(
            x in {".", ".."}
            or x.endswith((" ", "."))
            or x.casefold() in DENIED_PARTS
            or x.casefold().startswith(".env")
            for x in p.parts
        )
        and not any(ch in name for ch in ("\\", ":", "\x00"))
        and not any(ord(ch) < 32 for ch in name)
    )


def isolation():
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"NoNewPrivs", "Seccomp", "CapEff"}:
            status[key] = value.strip()
    readonly = False
    try:
        Path("/caliburn-write-probe").write_text("probe")
    except OSError:
        readonly = True
    status["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    status.update(
        uid=os.getuid(),
        root_readonly=readonly,
        docker_socket=Path("/var/run/docker.sock").exists(),
        interfaces=[name for _, name in socket.if_nameindex()],
    )
    for name, filename in (
        ("memory_max", "memory.max"),
        ("pids_max", "pids.max"),
        ("cpu_max", "cpu.max"),
    ):
        p = Path("/sys/fs/cgroup") / filename
        if p.exists():
            status[name] = p.read_text().strip()
    return status


def run(request):
    if set(request) != {"files", "digest", "operation"}:
        raise ValueError()
    files = request["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= 128:
        raise ValueError()
    folded, total = set(), 0
    for name, content in files.items():
        if not path_ok(name) or not isinstance(content, str) or "\x00" in content:
            raise ValueError()
        if name.casefold() in folded:
            raise ValueError()
        folded.add(name.casefold())
        size = len(content.encode())
        if size > 65536:
            raise ValueError()
        total += size
    if total > 1048576 or request["digest"] != digest(files):
        raise ValueError()
    if any(str(p) in files for name in files for p in PurePosixPath(name).parents):
        raise ValueError()
    # No archive extraction, symlinks, executable bit, mount or host path.
    for name, content in files.items():
        p = Path("/work") / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    op = request["operation"]
    if set(op) != {"tool", "arguments"} or not isinstance(op["arguments"], dict):
        raise ValueError()
    args = op["arguments"]
    tool = op["tool"]
    if tool == "repo_list" and not args:
        data = {
            "files": [
                {
                    "path": name,
                    "bytes": len(content.encode()),
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                }
                for name, content in sorted(files.items())
            ],
            "bundle_sha256": request["digest"],
        }
    elif tool == "repo_read" and set(args) == {"path", "start_line", "max_lines"}:
        name = args["path"]
        start, count = args["start_line"], args["max_lines"]
        if not path_ok(name) or type(start) is not int or type(count) is not int:
            raise ValueError()
        if not 1 <= start <= 100000 or not 1 <= count <= 200:
            raise ValueError()
        content = files[name]
        lines = content.splitlines()
        selected = "\n".join(lines[start - 1 : start - 1 + count])
        data = {
            "path": name,
            "content": selected[:16384],
            "truncated": len(selected) > 16384,
            "start_line": start,
            "total_lines": len(lines),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
    elif tool == "repo_search" and set(args) == {"text", "max_matches"}:
        needle, maximum = args["text"], args["max_matches"]
        if (
            not isinstance(needle, str)
            or not 1 <= len(needle) <= 200
            or type(maximum) is not int
            or not 1 <= maximum <= 100
        ):
            raise ValueError()
        matches = []
        for name, content in sorted(files.items()):
            for number, line in enumerate(content.splitlines(), 1):
                if needle in line:
                    matches.append({"path": name, "line": number, "text": line[:512]})
                    if len(matches) >= maximum:
                        break
            if len(matches) >= maximum:
                break
        data = {"matches": matches, "limit_reached": len(matches) == maximum}
    elif tool == "repo_patch" and set(args) in (
        {"path", "expected_sha256", "old", "new"},
        {"path", "expected_sha256", "old", "new", "parent_candidate_ref"},
    ):
        parent = args.get("parent_candidate_ref")
        if parent is not None and (not isinstance(parent, str) or len(parent) != 36):
            raise ValueError()
        name = args["path"]
        if not path_ok(name) or not all(
            isinstance(args[k], str) for k in ("path", "expected_sha256", "old", "new")
        ):
            raise ValueError()
        original = files[name]
        if hashlib.sha256(original.encode()).hexdigest() != args["expected_sha256"]:
            return {"ok": False, "error": "base_hash_mismatch"}
        if (
            not 1 <= len(args["old"]) <= 16384
            or len(args["new"]) > 16384
            or original.count(args["old"]) != 1
        ):
            return {"ok": False, "error": "patch_not_unique"}
        candidate = original.replace(args["old"], args["new"], 1)
        if len(candidate.encode()) > 65536:
            raise ValueError()
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(True),
                candidate.splitlines(True),
                fromfile="a/" + name,
                tofile="b/" + name,
            )
        )
        # Return inert candidate text/diff. Nothing is registered or executed.
        data = {
            "path": name,
            "base_sha256": args["expected_sha256"],
            "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
            "candidate": candidate,
            "diff": diff,
            "executable": False,
            "approved": False,
        }
    else:
        return {"ok": False, "error": "operation_denied"}
    return {"ok": True, "data": data}


def main():
    # Kernel-enforced lifetime also bounds a supervisor crash or stdin never arriving.
    signal.alarm(25)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError()
        result = run(json.loads(raw))
        result["isolation"] = isolation()
        output = json.dumps(result, ensure_ascii=True)
        if len(output.encode()) > MAX_OUTPUT:
            output = json.dumps({"ok": False, "error": "output_limit"})
    except (ValueError, TypeError, KeyError, OSError):
        output = json.dumps({"ok": False, "error": "invalid_workspace_request"})
    print(output)


if __name__ == "__main__":
    main()
