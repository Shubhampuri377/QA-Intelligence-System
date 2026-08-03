"""Runs every check and returns a non-zero exit code if any failed.

    venv\\Scripts\\python.exe tests\\run_all.py

Client feeds are read from %QA_TEST_DATA_DIR% (default: your Downloads folder)
and the checks that need them skip cleanly when they are not there — see
_harness.py. Nothing in this folder contains customer data.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
SUITES = ["test_reliability.py", "test_regression.py"]


def main():
    failed = []
    for name in SUITES:
        print("\n" + "#" * 60)
        print(f"# {name}")
        print("#" * 60)
        sys.stdout.flush()      # keep the header above the child's output
        r = subprocess.run([PY, os.path.join(HERE, name)], cwd=HERE)
        if r.returncode != 0:
            failed.append(name)

    print("\n" + "=" * 60)
    if failed:
        print("SUITES WITH FAILURES: " + ", ".join(failed))
    else:
        print("ALL SUITES PASSED")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
