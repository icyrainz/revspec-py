"""Review state — port of src/state/review-state.ts."""

from __future__ import annotations

import secrets
import string
import time

from .protocol import Thread, Message


def _nanoid(size: int = 8) -> str:
    alphabet = string.digits + string.ascii_lowercase
    return "".join(secrets.choice(alphabet) for _ in range(size))


class ReviewState:
    def __init__(self, spec_lines: list[str], threads: list[Thread] | None = None):
        self.spec_lines = spec_lines
        self.threads: list[Thread] = threads or []
        self.cursor_line: int = 1
        self._unread_thread_ids: set[str] = set()

    @property
    def line_count(self) -> int:
        return len(self.spec_lines)

    @property
    def unread_count(self) -> int:
        return len(self._unread_thread_ids)

    def add_comment(self, line: int, text: str) -> Thread:
        thread = Thread(
            id=_nanoid(),
            line=line,
            status="open",
            messages=[Message(author="reviewer", text=text, ts=int(time.time() * 1000))],
        )
        self.threads.append(thread)
        return thread

    def reply_to_thread(self, thread_id: str, text: str) -> None:
        t = self._find_thread(thread_id)
        if not t:
            return
        t.messages.append(Message(author="reviewer", text=text, ts=int(time.time() * 1000)))
        t.status = "open"

    def resolve_thread(self, thread_id: str) -> None:
        t = self._find_thread(thread_id)
        if not t:
            return
        t.status = "open" if t.status == "resolved" else "resolved"

    def resolve_all(self) -> None:
        for t in self.threads:
            if t.status not in ("resolved", "outdated"):
                t.status = "resolved"

    def resolve_all_pending(self) -> None:
        """Resolve only threads with pending status (AI-replied). Matches TS resolveAllPending."""
        for t in self.threads:
            if t.status == "pending":
                t.status = "resolved"

    def next_unread_thread(self) -> int | None:
        unread = [t for t in self.threads if t.id in self._unread_thread_ids]
        after = [t for t in unread if t.line > self.cursor_line]
        if after:
            return min(t.line for t in after)
        return min((t.line for t in unread), default=None)

    def prev_unread_thread(self) -> int | None:
        unread = [t for t in self.threads if t.id in self._unread_thread_ids]
        before = [t for t in unread if t.line < self.cursor_line]
        if before:
            return max(t.line for t in before)
        return max((t.line for t in unread), default=None)

    def delete_thread(self, thread_id: str) -> None:
        self.threads = [t for t in self.threads if t.id != thread_id]
        self._unread_thread_ids.discard(thread_id)

    def thread_at_line(self, line: int) -> Thread | None:
        for t in self.threads:
            if t.line == line:
                return t
        return None

    def next_thread(self) -> int | None:
        if not self.threads:
            return None
        after = [t for t in self.threads if t.line > self.cursor_line]
        if after:
            return min(t.line for t in after)
        return min(t.line for t in self.threads)

    def prev_thread(self) -> int | None:
        if not self.threads:
            return None
        before = [t for t in self.threads if t.line < self.cursor_line]
        if before:
            return max(t.line for t in before)
        return max(t.line for t in self.threads)

    def next_heading(self, level: int) -> int | None:
        prefix = "#" * level + " "
        guard = "#" * (level + 1)
        for i in range(self.cursor_line, len(self.spec_lines)):
            line = self.spec_lines[i]
            if line.startswith(prefix) and not line.startswith(guard):
                return i + 1
        for i in range(0, self.cursor_line - 1):
            line = self.spec_lines[i]
            if line.startswith(prefix) and not line.startswith(guard):
                return i + 1
        return None

    def prev_heading(self, level: int) -> int | None:
        prefix = "#" * level + " "
        guard = "#" * (level + 1)
        for i in range(self.cursor_line - 2, -1, -1):
            line = self.spec_lines[i]
            if line.startswith(prefix) and not line.startswith(guard):
                return i + 1
        for i in range(len(self.spec_lines) - 1, self.cursor_line - 1, -1):
            line = self.spec_lines[i]
            if line.startswith(prefix) and not line.startswith(guard):
                return i + 1
        return None

    def can_approve(self) -> bool:
        if not self.threads:
            return True
        return all(t.status in ("resolved", "outdated") for t in self.threads)

    def active_thread_count(self) -> tuple[int, int]:
        open_count = sum(1 for t in self.threads if t.status == "open")
        pending = sum(1 for t in self.threads if t.status == "pending")
        return open_count, pending

    def add_owner_reply(self, thread_id: str, text: str, ts: int | None = None) -> None:
        t = self._find_thread(thread_id)
        if not t:
            return
        t.messages.append(Message(author="owner", text=text, ts=ts))
        t.status = "pending"
        self._unread_thread_ids.add(thread_id)

    def is_unread(self, thread_id: str) -> bool:
        return thread_id in self._unread_thread_ids

    def mark_read(self, thread_id: str) -> None:
        self._unread_thread_ids.discard(thread_id)

    def reset(self, new_lines: list[str]) -> None:
        self.spec_lines = new_lines
        self.threads = []
        self.cursor_line = 1
        self._unread_thread_ids.clear()

    def _find_thread(self, thread_id: str) -> Thread | None:
        for t in self.threads:
            if t.id == thread_id:
                return t
        return None
