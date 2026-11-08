"""Container-only JSON observation. No expected values or pass authority enter here."""

import importlib.util
import json
import signal
import sys
from pathlib import Path
from runpy import run_path

helpers = run_path("/opt/runner.py")


def main():
    signal.alarm(3)
    try:
        request = json.loads(sys.stdin.buffer.read(2097153))
        if set(request) != {"files", "source_sha256", "entrypoint", "input"}:
            raise ValueError()
        files = request["files"]
        # Reuse bounded inert materialization; candidate code is imported only below.
        helpers["run"](
            {
                "files": files,
                "digest": request["source_sha256"],
                "operation": {"tool": "repo_list", "arguments": {}},
            }
        )
        path, separator, symbol = request["entrypoint"].partition(":")
        if (
            not separator
            or path not in files
            or not symbol.isidentifier()
            or not isinstance(request["input"], dict)
        ):
            raise ValueError()
        sys.path.insert(0, "/work")
        spec = importlib.util.spec_from_file_location("_oracle_subject", Path("/work") / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = getattr(module, symbol)(**request["input"])
        output = json.dumps({"value": value}, ensure_ascii=True, allow_nan=False)
        if len(output.encode()) > 32768:
            raise ValueError()
        print(output)
    except BaseException:  # noqa: BLE001 -- subject SystemExit must never imply success
        # No traceback/source/exception text; zero exit without a value is never a pass.
        sys.exit(1)


if __name__ == "__main__":
    main()
