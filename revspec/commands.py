"""Pure command parsing for :command mode."""

from __future__ import annotations

from dataclasses import dataclass, field


_FORCE_QUIT = frozenset({"q!", "qa!", "wq!", "wqa!", "qw!", "qwa!"})
_SAFE_QUIT = frozenset({"q", "qa", "wq", "wqa", "qw", "qwa"})


@dataclass
class CommandResult:
    """Parsed result of a :command."""

    action: str  # "force_quit", "quit", "submit", "approve", "help",
    #               "resolve", "reload", "wrap", "goto", "unknown"
    args: dict = field(default_factory=dict)


def parse_command(raw: str) -> CommandResult:
    """Parse a raw command string into a CommandResult.

    Returns a CommandResult with action="unknown" for unrecognized commands.
    """
    cmd = raw.strip()

    if cmd in _FORCE_QUIT:
        return CommandResult(action="force_quit")

    if cmd in _SAFE_QUIT:
        return CommandResult(action="quit")

    if cmd == "submit":
        return CommandResult(action="submit")

    if cmd == "approve":
        return CommandResult(action="approve")

    if cmd == "help":
        return CommandResult(action="help")

    if cmd == "resolve":
        return CommandResult(action="resolve")

    if cmd == "reload":
        return CommandResult(action="reload")

    if cmd == "wrap":
        return CommandResult(action="wrap")

    if cmd == "diff":
        return CommandResult(action="diff")

    # Try line number
    try:
        line_num = int(cmd)
        if line_num <= 0:
            return CommandResult(action="unknown", args={"raw": cmd})
        return CommandResult(action="goto", args={"line": line_num})
    except ValueError:
        return CommandResult(action="unknown", args={"raw": cmd})
