"""DiffState — line-level diff computation between two spec versions."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher


class DiffState:
    """Computes and exposes line-level diff between two spec versions.

    Uses difflib.SequenceMatcher with autojunk=False to prevent blank lines
    (common in markdown) from being treated as junk.
    """

    def __init__(self, old_lines: list[str], new_lines: list[str]) -> None:
        self._added: set[int] = set()
        self._removed_blocks: dict[int, list[str]] = {}
        self._hunk_starts: list[int] = []
        self._is_active: bool = True
        self._new_len: int = len(new_lines)

        sm = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        added_count = 0
        removed_count = 0
        hunk_set: set[int] = set()

        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            elif op == "insert":
                for j in range(j1, j2):
                    self._added.add(j)
                added_count += j2 - j1
                hunk_set.add(j1)
            elif op == "delete":
                self._removed_blocks[j1] = old_lines[i1:i2]
                removed_count += i2 - i1
                hunk_set.add(j1)
            elif op == "replace":
                self._removed_blocks[j1] = old_lines[i1:i2]
                removed_count += i2 - i1
                for j in range(j1, j2):
                    self._added.add(j)
                added_count += j2 - j1
                hunk_set.add(j1)

        self._stats = (added_count, removed_count)
        self._hunk_starts = sorted(hunk_set)

    def is_added(self, new_idx: int) -> bool:
        return new_idx in self._added

    def removed_lines_before(self, new_idx: int) -> list[str]:
        return self._removed_blocks.get(new_idx, [])

    def has_diff(self) -> bool:
        return bool(self._added or self._removed_blocks)

    def toggle(self) -> bool:
        self._is_active = not self._is_active
        return self._is_active

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def stats(self) -> tuple[int, int]:
        return self._stats

    def next_hunk(self, current_spec_line: int) -> int | None:
        if not self._hunk_starts:
            return None
        current_idx = current_spec_line - 1
        pos = bisect_right(self._hunk_starts, current_idx)
        if pos >= len(self._hunk_starts):
            return None
        hunk_idx = self._hunk_starts[pos]
        # A trailing delete hunk sits at new_len (past the last line);
        # clamp to new_len so it maps to spec line new_len rather than new_len+1.
        return min(hunk_idx + 1, self._new_len)

    def prev_hunk(self, current_spec_line: int) -> int | None:
        if not self._hunk_starts:
            return None
        current_idx = current_spec_line - 1
        pos = bisect_left(self._hunk_starts, current_idx)
        if pos <= 0:
            return None
        hunk_idx = self._hunk_starts[pos - 1]
        return min(hunk_idx + 1, self._new_len)
