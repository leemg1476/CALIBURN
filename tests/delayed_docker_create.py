"""Maintained subprocess fixture: emulate a slow Docker create daemon request."""

import subprocess
import sys
import time

if __name__ == "__main__":
    if sys.argv[1:3] != ["docker", "create"]:
        raise SystemExit("Only the create fixture is allowed")
    time.sleep(0.2)
    raise SystemExit(subprocess.run(sys.argv[1:], check=False).returncode)
