"""Pure navigation utilities — jump list and heading breadcrumb."""

from __future__ import annotations

import re


class JumpList:
    """Fixed-size jump history with forward/backward/swap.

    Mirrors vim's :jumps behavior (TS app.ts:161-184).
    """

    def __init__(self, max_size: int = 50) -> None:
        self._entries: list[int] = [1]
        self._index: int = 0
        self._max_size = max_size

    def push(self, current: int) -> None:
        """Record position before a big jump. Deduplicates tail."""
        if self._index < len(self._entries) - 1:
            self._entries[self._index + 1 :] = []
        if self._entries and self._entries[-1] == current:
            return
        self._entries.append(current)
        if len(self._entries) > self._max_size:
            self._entries.pop(0)
        self._index = len(self._entries) - 1

    def backward(self, current: int, line_count: int) -> int | None:
        """Ctrl+O — jump back. Returns target line or None."""
        if self._index == len(self._entries) - 1:
            if self._entries[self._index] != current:
                self._entries.append(current)
                if len(self._entries) > self._max_size:
                    self._entries.pop(0)
                self._index = len(self._entries) - 1
        if self._index > 0:
            self._index -= 1
            return min(self._entries[self._index], line_count)
        return None

    def forward(self, line_count: int) -> int | None:
        """Ctrl+I / Tab — jump forward. Returns target line or None."""
        if self._index < len(self._entries) - 1:
            self._index += 1
            return min(self._entries[self._index], line_count)
        return None

    def swap(self, current: int, line_count: int) -> int | None:
        """'' — swap between current and previous entry. Returns target or None."""
        if len(self._entries) < 2:
            return None
        if self._index == 0:
            target_idx = 1
        else:
            target_idx = self._index - 1
        target = self._entries[target_idx]
        self._entries[self._index] = current
        self._index = target_idx
        return min(target, line_count)


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)")


def heading_breadcrumb(spec_lines: list[str], cursor_line: int) -> str | None:
    """Find the nearest heading above cursor_line (1-based). Returns heading text or None."""
    for i in range(cursor_line - 1, -1, -1):
        m = _HEADING_RE.match(spec_lines[i])
        if m:
            return m.group(2).strip()
    return None
