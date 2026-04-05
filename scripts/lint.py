#!/usr/bin/env python3
"""Run ruff linting on the codebase.

Usage:
    python scripts/lint.py           # Check for issues
    python scripts/lint.py --fix     # Auto-fix issues (including unsafe fixes)
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PATHS = ["graph_kb_api/", "graph_kb_dashboard/src/"]


def main():
    fix_mode = "--fix" in sys.argv or "-f" in sys.argv

    cmd = ["ruff", "check"]
    cmd.extend(PATHS)

    if fix_mode:
        cmd.extend(["--fix", "--unsafe-fixes"])
        print("Running ruff with auto-fix...")
    else:
        print("Running ruff linting...")

    result = subprocess.run(cmd, cwd=REPO_ROOT)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
