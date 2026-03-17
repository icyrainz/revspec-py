#!/usr/bin/env python3
"""revspec — terminal-based spec review tool."""

import sys
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: revspec <file.md>")
        print("       revspec watch <file.md>")
        print('       revspec reply <file.md> <threadId> "<text>"')
        sys.exit(0)

    if "--version" in args or "-v" in args:
        from importlib.metadata import version
        print(f"revspec {version('revspec')} (python)")
        sys.exit(0)

    # Subcommand routing
    if args[0] == "reply":
        if len(args) < 4:
            print('Usage: revspec reply <file.md> <threadId> "<text>"', file=sys.stderr)
            sys.exit(1)
        from revspec.reply import run_reply
        run_reply(args[1], args[2], args[3])
        return

    if args[0] == "watch":
        if len(args) < 2:
            print("Usage: revspec watch <file.md>", file=sys.stderr)
            sys.exit(1)
        from revspec.watch import run_watch
        run_watch(args[1])
        return

    # Default: launch TUI
    spec_file = next((a for a in args if not a.startswith("--")), None)
    if not spec_file:
        print("Error: No spec file provided", file=sys.stderr)
        sys.exit(1)

    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    from revspec.app import RevspecApp

    app = RevspecApp(str(spec_path))
    app.run()


if __name__ == "__main__":
    main()
