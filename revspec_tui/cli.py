#!/usr/bin/env python3
"""revspec — terminal-based spec review tool."""

import sys
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: revspec <file.md>")
        sys.exit(0)

    if "--version" in args or "-v" in args:
        from importlib.metadata import version
        print(f"revspec {version('revspec')}")
        sys.exit(0)

    spec_file = next((a for a in args if not a.startswith("--")), None)
    if not spec_file:
        print("Error: No spec file provided", file=sys.stderr)
        sys.exit(1)

    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    from revspec_tui.app import RevspecApp

    app = RevspecApp(str(spec_path))
    app.run()


if __name__ == "__main__":
    main()
