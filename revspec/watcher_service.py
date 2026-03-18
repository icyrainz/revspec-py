"""Live watcher service — JSONL polling and watcher detection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import LiveEvent, read_events


@dataclass
class PollResult:
    """Result of polling for new events."""

    events: list[LiveEvent] = field(default_factory=list)
    has_new: bool = False


class LiveWatcherService:
    """Polls JSONL for new events since last offset."""

    def __init__(self, jsonl_path: str) -> None:
        self._jsonl_path = jsonl_path
        self._offset = 0

    def init_offset(self) -> None:
        """Set offset to current file size (skip existing events)."""
        if os.path.exists(self._jsonl_path):
            self._offset = os.path.getsize(self._jsonl_path)

    def poll(self) -> PollResult:
        """Read new events since last poll. Advances offset."""
        try:
            events, new_offset = read_events(self._jsonl_path, self._offset)
            self._offset = new_offset
            if events:
                owner_events = [e for e in events if e.author == "owner"]
                return PollResult(events=owner_events, has_new=bool(owner_events))
            return PollResult()
        except OSError:
            return PollResult()

    def reset_offset(self) -> None:
        self._offset = 0


def is_watcher_running(spec_file: str) -> bool:
    """Check if a revspec watch process is monitoring this review."""
    base = Path(spec_file)
    lock_path = base.parent / (base.stem + ".review.lock")
    if not lock_path.exists():
        return False
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check if process exists
        return True
    except (ValueError, OSError):
        return False
