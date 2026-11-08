"""Actual HTTP/worker/Docker candidate → separate operator Git checkout CLI.

Inference/source are offline fixtures. No source execution, approval or remote write.
Requires a migrated disposable PostgreSQL database and the fixed data image.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from demo_workspace import demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-root", default=".caliburn/checkouts")
    args = parser.parse_args()
    evidence = demo(args.image, output=Path("docs/evidence/m2-checkout-source-task.json"))
    root = Path(args.output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "caliburn.sandbox.checkout",
            "--task",
            evidence["task_id"],
            "--candidate",
            evidence["candidate_ref"],
            "--output-root",
            str(root),
        ],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=70,
        check=False,
    )
    if result.returncode:
        raise SystemExit("Operator checkout demo failed; output withheld")
    exported = json.loads(result.stdout)
    directory = Path(exported["directory"])
    patch = (directory / "candidate.patch").read_text(encoding="utf-8")
    assert "-    return a - b" in patch and "+    return a + b" in patch
    assert exported["manifest"]["source_executed"] is False
    report = {
        "inference": "scripted offline fixture (mock)",
        "transport": evidence["transport"],
        "task_id": evidence["task_id"],
        "state": evidence["state"],
        "checkout": exported,
        "git_diff": patch,
        "source_executed": False,
        "remote_write": False,
        "scope": "operator handoff only; reconstructed granted snapshot, no original history clone",
    }
    Path("docs/evidence/m2-task-checkout-demo.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "task_state": evidence["state"],
                "checkout": str(directory),
                "diff_sha256": exported["manifest"]["diff_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
