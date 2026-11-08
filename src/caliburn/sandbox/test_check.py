"""Fixed child entry point; runs inside the disposable container only."""

import sys
import unittest


def main():
    sys.path.insert(0, "/work/src")
    suite = unittest.defaultTestLoader.discover("/work/tests", pattern="test_*.py")
    if suite.countTestCases() == 0:
        raise SystemExit(2)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
