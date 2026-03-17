# Full Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Achieve 1:1 feature parity between the Python/Textual revspec port and the TypeScript/Bun original.

**Architecture:** Foundation-first — navigation primitives and state methods first, then thread popup overhaul, then rendering, then status bar polish, then CLI subcommands, then tests. Each batch builds on the previous. The TS source at `/home/akio/repo/revspec/src/` is the authoritative reference for all behavior.

**Tech Stack:** Python 3.11+, Textual 1.x, Rich, pytest

**Test runner:** `.venv/bin/python -m pytest`

**Key constraint:** No native dependencies. Polling-only for file watching. Performance matters — avoid O(n) work on every keypress where possible.

---

## Chunk 1: State Layer + Navigation Primitives (Batch 1)

### Task 1: Add state methods — unread thread navigation + resolve_all_pending

**Files:**
- Modify: `revspec_tui/state.py:49-58` (add methods after `resolve_thread`)
- Create: `tests/test_state.py`

**TS ref:** `review-state.ts:65-71`, `review-state.ts:209-221`

- [ ] **Step 0: Create tests directory**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 1: Create test file with tests for new state methods**

```python
# tests/test_state.py
"""Tests for ReviewState."""
import pytest
from revspec_tui.state import ReviewState
from revspec_tui.protocol import Thread, Message


def _make_state(n_lines=20):
    return ReviewState([f"line {i}" for i in range(n_lines)])


def _add_thread(state, line, status="open", thread_id=None, unread=False):
    t = state.add_comment(line, f"comment on {line}")
    t.status = status
    if thread_id:
        t.id = thread_id
    if unread:
        state._unread_thread_ids.add(t.id)
    return t


class TestResolveAllPending:
    def test_resolves_only_pending(self):
        state = _make_state()
        t1 = _add_thread(state, 1, status="open")
        t2 = _add_thread(state, 5, status="pending")
        t3 = _add_thread(state, 10, status="resolved")
        state.resolve_all_pending()
        assert t1.status == "open"
        assert t2.status == "resolved"
        assert t3.status == "resolved"

    def test_noop_when_no_pending(self):
        state = _make_state()
        _add_thread(state, 1, status="open")
        state.resolve_all_pending()
        assert state.threads[0].status == "open"


class TestNextUnreadThread:
    def test_finds_next_after_cursor(self):
        state = _make_state()
        _add_thread(state, 3, unread=True)
        _add_thread(state, 8, unread=True)
        state.cursor_line = 1
        assert state.next_unread_thread() == 3

    def test_wraps_around(self):
        state = _make_state()
        _add_thread(state, 3, unread=True)
        state.cursor_line = 10
        assert state.next_unread_thread() == 3

    def test_returns_none_when_no_unread(self):
        state = _make_state()
        _add_thread(state, 3, status="open")
        state.cursor_line = 1
        assert state.next_unread_thread() is None


class TestPrevUnreadThread:
    def test_finds_prev_before_cursor(self):
        state = _make_state()
        _add_thread(state, 3, unread=True)
        _add_thread(state, 8, unread=True)
        state.cursor_line = 10
        assert state.prev_unread_thread() == 8

    def test_wraps_around(self):
        state = _make_state()
        _add_thread(state, 8, unread=True)
        state.cursor_line = 3
        assert state.prev_unread_thread() == 8

    def test_returns_none_when_no_unread(self):
        state = _make_state()
        state.cursor_line = 5
        assert state.prev_unread_thread() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_state.py -v`
Expected: FAIL — `resolve_all_pending`, `next_unread_thread`, `prev_unread_thread` not defined

- [ ] **Step 3: Implement the three methods in state.py**

Add after `resolve_all` (line 58):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_state.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_state.py revspec_tui/state.py
git commit -m "feat(state): add resolve_all_pending, next/prev_unread_thread"
```

---

### Task 2: Jump list infrastructure in app.py

**Files:**
- Modify: `revspec_tui/app.py:499-527` (RevspecApp.__init__, add jump list state + methods)

**TS ref:** `app.ts:161-184`

- [ ] **Step 1: Add jump list state and methods to RevspecApp.__init__**

After `self._pending_timer` (line 526), add:

```python
# Jump list — mirrors vim :jumps (TS app.ts:161-184)
self._jump_list: list[int] = [1]
self._jump_index: int = 0
self.MAX_JUMP_LIST = 50

# Track scroll position for H/M/L (SpecPager extends Static, no scroll_offset)
self._scroll_y: int = 0
```

- [ ] **Step 2: Add push_jump and related methods**

Add after `_show_transient` method:

```python
def _push_jump(self) -> None:
    """Record current position in jump list before a big jump."""
    cur = self.state.cursor_line
    # Discard forward history when jumping from middle of list
    if self._jump_index < len(self._jump_list) - 1:
        self._jump_list[self._jump_index + 1:] = []
    # Don't push duplicate of tail
    if self._jump_list and self._jump_list[-1] == cur:
        return
    self._jump_list.append(cur)
    if len(self._jump_list) > self.MAX_JUMP_LIST:
        self._jump_list.pop(0)
    self._jump_index = len(self._jump_list) - 1

def _jump_backward(self) -> None:
    """Ctrl+O — jump back in jump list."""
    # On first backward traversal from head, save current position
    if self._jump_index == len(self._jump_list) - 1:
        cur = self.state.cursor_line
        if self._jump_list[self._jump_index] != cur:
            self._jump_list.append(cur)
            if len(self._jump_list) > self.MAX_JUMP_LIST:
                self._jump_list.pop(0)
            self._jump_index = len(self._jump_list) - 1
    if self._jump_index > 0:
        self._jump_index -= 1
        self.state.cursor_line = min(self._jump_list[self._jump_index], self.state.line_count)
        self._refresh()

def _jump_forward(self) -> None:
    """Ctrl+I / Tab — jump forward in jump list."""
    if self._jump_index < len(self._jump_list) - 1:
        self._jump_index += 1
        self.state.cursor_line = min(self._jump_list[self._jump_index], self.state.line_count)
        self._refresh()

def _jump_swap(self) -> None:
    """'' — swap between current position and last jump entry."""
    if len(self._jump_list) > 1:
        cur = self.state.cursor_line
        prev_idx = max(0, self._jump_index - 1)
        target = self._jump_list[prev_idx]
        self._jump_list[self._jump_index] = cur
        self._jump_index = prev_idx
        self.state.cursor_line = min(target, self.state.line_count)
        self._refresh()
```

- [ ] **Step 3: Wire jump list keys into on_key**

In `on_key` method, add before the match statement (after `event.prevent_default()`):

```python
# Ctrl+O: jump back
case "ctrl+o":
    self._jump_backward()
# Ctrl+I / Tab: jump forward (only when no overlay active)
case "tab":
    self._jump_forward()
```

And add `apostrophe` to the pending-key set (line 611):
```python
if key in ("g", "z", "d", "bracketleft", "bracketright", "apostrophe"):
```

Add to `_handle_sequence`:
```python
case "apostropheapostrophe":  # ''
    self._jump_swap()
```

- [ ] **Step 3b: Update _scroll_to_cursor to track _scroll_y**

In `_scroll_to_cursor`, after computing the scroll target, store it:

```python
def _scroll_to_cursor(self) -> None:
    if self.pager_widget:
        target = max(0, self.state.cursor_line - self.size.height // 2)
        self._scroll_y = target
        self.pager_widget.scroll_to(y=target)
```

- [ ] **Step 4: Add push_jump calls to all big-jump handlers**

Add `self._push_jump()` before cursor movement in:
- `G` handler (line 637)
- `gg` handler (in `_handle_sequence`, line 670)
- `n` / `N` handlers (before `self.state.cursor_line = i + 1`)
- `]t` / `[t` handlers (before `self.state.cursor_line = line`)
- `]1-3` / `[1-3` — in `_jump_heading`
- `:N` command — in `_process_command` before `self.state.cursor_line = line_num`
- Thread list `on_result` callback — before `self.state.cursor_line = line`
- Search `on_result` callback — before `self.state.cursor_line = line`

- [ ] **Step 5: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: add jump list (Ctrl+O/I, '' swap) with push_jump at all jump sites"
```

---

### Task 3: Add ]r/[r, R, H/M/L, fix zz, smartcase fix, confirm q key

**Files:**
- Modify: `revspec_tui/app.py` (key handlers, ConfirmScreen, SpecPager)

- [ ] **Step 1: Add ]r/[r sequences to _handle_sequence**

```python
case "bracketrightr":  # ]r next unread
    line = self.state.next_unread_thread()
    if line:
        self._push_jump()
        self.state.cursor_line = line
        self._refresh()
    else:
        self._show_transient("No unread replies")
case "bracketleftr":  # [r prev unread
    line = self.state.prev_unread_thread()
    if line:
        self._push_jump()
        self.state.cursor_line = line
        self._refresh()
    else:
        self._show_transient("No unread replies")
```

- [ ] **Step 2: Add R key handler in on_key match**

```python
case "shift+r" | "R":
    pending_threads = [t for t in self.state.threads if t.status == "pending"]
    if not pending_threads:
        self._show_transient("No pending threads")
    else:
        self.state.resolve_all_pending()
        for t in pending_threads:
            append_event(self.jsonl_path, LiveEvent(
                type="resolve", thread_id=t.id,
                author="reviewer", ts=int(time.time() * 1000),
            ))
        self._refresh()
        self._show_transient(f"Resolved {len(pending_threads)} pending thread(s)")
```

- [ ] **Step 3: Add H/M/L key handlers in on_key match**

```python
case "shift+h" | "H":
    self._push_jump()
    # SpecPager extends Static (no scroll_offset). Track scroll via _scroll_y.
    scroll_top = self._scroll_y
    self.state.cursor_line = max(1, min(scroll_top + 1, self.state.line_count))
    self._refresh()
case "shift+m" | "M":
    self._push_jump()
    scroll_top = self._scroll_y
    page_h = max(1, self.size.height - 2)
    self.state.cursor_line = max(1, min(scroll_top + page_h // 2, self.state.line_count))
    self._refresh()
case "shift+l" | "L":
    self._push_jump()
    scroll_top = self._scroll_y
    page_h = max(1, self.size.height - 2)
    self.state.cursor_line = max(1, min(scroll_top + page_h - 1, self.state.line_count))
    self._refresh()
```

- [ ] **Step 4: Fix zz to actually center the cursor**

In `_handle_sequence`, replace the `"zz"` case:

```python
case "zz":
    if self.pager_widget:
        half_view = max(1, self.size.height - 2) // 2
        target = max(0, self.state.cursor_line - 1 - half_view)
        self.pager_widget.scroll_to(y=target)
    self._refresh()
```

- [ ] **Step 5: Fix smartcase in pager search highlighting**

In `SpecPager.render()`, replace line 87-88:

```python
# Search highlighting — respect smartcase
if self.search_query:
    case_sensitive = self.search_query != self.search_query.lower()
    q = self.search_query if case_sensitive else self.search_query.lower()
    c = content if case_sensitive else content.lower()
    if q in c:
        self._append_highlighted(text, content, self.search_query, content_style, is_cursor)
    else:
        text.append(content, content_style)
else:
    text.append(content, content_style)
```

And update `_append_highlighted` to use smartcase:

```python
def _append_highlighted(self, text, content, query, base_style, is_cursor):
    case_sensitive = query != query.lower()
    q = query if case_sensitive else query.lower()
    haystack = content if case_sensitive else content.lower()
    pos = 0
    while pos < len(content):
        idx = haystack.find(q, pos)
        if idx == -1:
            text.append(content[pos:], base_style)
            break
        if idx > pos:
            text.append(content[pos:idx], base_style)
        text.append(
            content[idx:idx + len(query)],
            Style(color="#1e1e2e", bgcolor=THEME["yellow"], bold=True),
        )
        pos = idx + len(query)
```

- [ ] **Step 5b: Add search wrap notifications to _search_next**

In `_search_next`, after finding a match, check if it wrapped:

```python
def _search_next(self, direction: int) -> None:
    if not self.search_query:
        self._show_transient("No active search \u2014 use / to search")
        return
    case_sensitive = self.search_query != self.search_query.lower()
    q = self.search_query if case_sensitive else self.search_query.lower()
    total = self.state.line_count
    for offset in range(1, total + 1):
        i = (self.state.cursor_line - 1 + offset * direction) % total
        line = self.state.spec_lines[i] if case_sensitive else self.state.spec_lines[i].lower()
        if q in line:
            match_line = i + 1
            wrapped = (direction == 1 and match_line <= self.state.cursor_line) or \
                      (direction == -1 and match_line >= self.state.cursor_line)
            self._push_jump()
            self.state.cursor_line = match_line
            self._refresh()
            if wrapped:
                msg = "Search wrapped to top" if direction == 1 else "Search wrapped to bottom"
                self._show_transient(msg, "info", 1.2)
            return
    self._show_transient("No matches")
```

- [ ] **Step 5c: Add wrap notifications to ]t/[t thread navigation**

In `_handle_sequence`, update the `bracketrightt` and `bracketleftt` cases:

```python
case "bracketrightt":  # ]t
    line = self.state.next_thread()
    if line:
        wrapped = line <= self.state.cursor_line
        self._push_jump()
        self.state.cursor_line = line
        self._refresh()
        if wrapped:
            self._show_transient("Wrapped to first thread", "info", 1.2)
    else:
        self._show_transient("No threads")
case "bracketleftt":  # [t
    line = self.state.prev_thread()
    if line:
        wrapped = line >= self.state.cursor_line
        self._push_jump()
        self.state.cursor_line = line
        self._refresh()
        if wrapped:
            self._show_transient("Wrapped to last thread", "info", 1.2)
    else:
        self._show_transient("No threads")
```

- [ ] **Step 6: Add q to ConfirmScreen**

In `ConfirmScreen.on_key`, change the cancel check:

```python
elif event.key in ("n", "q", "escape"):
    event.prevent_default()
    self.dismiss(False)
```

Also update the hint text:

```python
yield Static("[y/Enter] Confirm  [q/Esc] Cancel", id="confirm-hints")
```

- [ ] **Step 7: Run existing tests + manual verification**

Run: `.venv/bin/python -m pytest tests/test_state.py -v`
Expected: All PASS (state tests still pass)

- [ ] **Step 8: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: add ]r/[r, R, H/M/L, fix zz centering, fix smartcase, add q to confirm"
```

---

## Chunk 2: Thread Popup Overhaul (Batch 2)

### Task 4: Extract and rewrite CommentScreen with vim modes

**Files:**
- Create: `revspec_tui/comment_screen.py`
- Modify: `revspec_tui/app.py:22-26` (imports), `revspec_tui/app.py:716-741` (_open_comment)

This is the biggest single change. The CommentScreen goes from a simple modal to a full vim-mode popup with conversation history, persistence, and resolve toggle.

**TS ref:** `comment-input.ts` (entire file)

- [ ] **Step 1: Create comment_screen.py with the new CommentScreen**

```python
# revspec_tui/comment_screen.py
"""Thread popup with vim normal/insert modes — port of comment-input.ts."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea
from rich.text import Text
from rich.style import Style

from collections.abc import Callable

from .protocol import Thread, Message
from .theme import THEME

# Hint text per mode
NORMAL_HINTS = "[NORMAL]  [i/c] reply  [r] resolve  [q/Esc] close"
INSERT_HINTS = "[INSERT]  [Tab] send  [Esc] normal"


class CommentResult:
    """Result from CommentScreen — encodes what happened."""
    __slots__ = ("action", "text", "thread_id")

    def __init__(self, action: str, text: str | None = None, thread_id: str | None = None):
        self.action = action  # "cancel", "resolve"
        self.text = text
        self.thread_id = thread_id


class CommentScreen(ModalScreen[CommentResult]):
    """Modal thread popup with vim normal/insert modes.

    - New thread: starts in INSERT mode (green border, textarea focused)
    - Existing thread: starts in NORMAL mode (blue border, read conversation)
    - Tab submits text but does NOT dismiss — popup persists for conversation
    - r in normal mode triggers resolve
    - q/Esc in normal mode dismisses
    """

    CSS = """
    CommentScreen { align: center middle; }
    #comment-dialog {
        width: 70;
        height: 80%;
        border: solid #89b4fa;
        background: #313244;
        padding: 1 2;
    }
    #comment-title {
        text-style: bold;
        color: #89b4fa;
        margin-bottom: 1;
    }
    #comment-history {
        height: 1fr;
        overflow-y: auto;
    }
    #comment-separator {
        height: 1;
        border-top: solid #45475a;
    }
    #comment-input {
        height: 4;
        min-height: 4;
    }
    #comment-hints {
        color: #6c7086;
        height: 1;
    }
    """

    def __init__(
        self,
        line: int,
        existing_thread: Thread | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_resolve: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.line = line
        self.existing_thread = existing_thread
        self._on_submit = on_submit
        self._on_resolve = on_resolve
        self._mode: str = "normal" if existing_thread and existing_thread.messages else "insert"
        self._pending_g: bool = False

    def compose(self) -> ComposeResult:
        thread = self.existing_thread
        title = (
            f"Thread #{thread.id} (line {self.line})"
            if thread and thread.id
            else f"New comment on line {self.line}"
        )
        with Vertical(id="comment-dialog"):
            yield Static(title, id="comment-title")
            with VerticalScroll(id="comment-history"):
                if thread:
                    for msg in thread.messages:
                        yield self._render_message(msg)
            yield Static("", id="comment-separator")
            yield TextArea(id="comment-input")
            hints = NORMAL_HINTS if self._mode == "normal" else INSERT_HINTS
            yield Static(hints, id="comment-hints")

    def on_mount(self) -> None:
        if self._mode == "insert":
            self._enter_insert()
        else:
            self._enter_normal()
        # Scroll conversation to bottom
        history = self.query_one("#comment-history", VerticalScroll)
        history.scroll_end(animate=False)

    def _render_message(self, msg: Message) -> Static:
        is_reviewer = msg.author == "reviewer"
        prefix = "You" if is_reviewer else "AI"
        color = THEME["blue"] if is_reviewer else THEME["green"]
        text = Text()
        text.append(f"{prefix}: ", Style(color=color, bold=True))
        text.append(msg.text)
        return Static(text)

    def add_message(self, msg: Message) -> None:
        """Push a message into the conversation (for live watcher)."""
        history = self.query_one("#comment-history", VerticalScroll)
        history.mount(self._render_message(msg))
        history.scroll_end(animate=False)

    def _enter_insert(self) -> None:
        self._mode = "insert"
        textarea = self.query_one("#comment-input", TextArea)
        textarea.focus()
        self.query_one("#comment-hints", Static).update(INSERT_HINTS)
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.styles.border = ("solid", THEME["green"])

    def _enter_normal(self) -> None:
        self._mode = "normal"
        # Blur textarea by focusing the dialog itself
        self.query_one("#comment-dialog", Vertical).focus()
        self.query_one("#comment-hints", Static).update(NORMAL_HINTS)
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.styles.border = ("solid", THEME["blue"])

    def on_key(self, event: Key) -> None:
        if self._mode == "insert":
            self._handle_insert_key(event)
        else:
            self._handle_normal_key(event)

    def _handle_insert_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self._enter_normal()
        elif event.key == "tab":
            event.prevent_default()
            event.stop()
            textarea = self.query_one("#comment-input", TextArea)
            text = textarea.text.strip()
            if not text:
                return
            # Submit callback — app handles state + JSONL
            if self._on_submit:
                self._on_submit(text)
            # Append to conversation display
            self.add_message(Message(author="reviewer", text=text))
            # Clear textarea and switch to normal
            textarea.clear()
            self._enter_normal()
        # All other keys pass through to textarea

    def _handle_normal_key(self, event: Key) -> None:
        event.prevent_default()
        event.stop()
        key = event.key

        if key in ("escape", "q"):
            self.dismiss(CommentResult("cancel"))
        elif key in ("i", "c"):
            self._enter_insert()
        elif key == "r":
            if self._on_resolve:
                self._on_resolve()
            self.dismiss(CommentResult("resolve"))
        elif key in ("j", "down"):
            self.query_one("#comment-history", VerticalScroll).scroll_down()
        elif key in ("k", "up"):
            self.query_one("#comment-history", VerticalScroll).scroll_up()
        elif key == "ctrl+d":
            h = self.query_one("#comment-history", VerticalScroll)
            h.scroll_to(y=h.scroll_offset.y + 5)
        elif key == "ctrl+u":
            h = self.query_one("#comment-history", VerticalScroll)
            h.scroll_to(y=max(0, h.scroll_offset.y - 5))
        elif key == "g":
            if self._pending_g:
                self._pending_g = False
                self.query_one("#comment-history", VerticalScroll).scroll_home()
            else:
                self._pending_g = True
                self.set_timer(0.3, self._clear_pending_g)
        elif key in ("shift+g", "G"):
            self._pending_g = False
            self.query_one("#comment-history", VerticalScroll).scroll_end()

    def _clear_pending_g(self) -> None:
        self._pending_g = False
```

- [ ] **Step 2: Update app.py imports and _open_comment**

Replace the CommentScreen import and rewrite `_open_comment`:

```python
# In imports at top of app.py
from .comment_screen import CommentScreen, CommentResult

# Rewrite _open_comment method
def _open_comment(self) -> None:
    thread = self.state.thread_at_line(self.state.cursor_line)

    def on_submit(text: str) -> None:
        nonlocal thread
        if thread:
            self.state.reply_to_thread(thread.id, text)
            self.state.mark_read(thread.id)
            append_event(self.jsonl_path, LiveEvent(
                type="reply", thread_id=thread.id,
                author="reviewer", text=text, ts=int(time.time() * 1000),
            ))
        else:
            new_thread = self.state.add_comment(self.state.cursor_line, text)
            append_event(self.jsonl_path, LiveEvent(
                type="comment", thread_id=new_thread.id,
                line=self.state.cursor_line, author="reviewer",
                text=text, ts=int(time.time() * 1000),
            ))
            thread = new_thread  # Subsequent submits are replies
        self._refresh()

    def on_resolve() -> None:
        if thread:
            was_resolved = thread.status == "resolved"
            self.state.resolve_thread(thread.id)
            self.state.mark_read(thread.id)
            event_type = "unresolve" if was_resolved else "resolve"
            append_event(self.jsonl_path, LiveEvent(
                type=event_type, thread_id=thread.id,
                author="reviewer", ts=int(time.time() * 1000),
            ))
            # Auto-advance to next thread only when resolving
            if not was_resolved:
                next_line = self.state.next_thread()
                if next_line is not None:
                    self.state.cursor_line = next_line
        self._refresh()

    screen = CommentScreen(
        self.state.cursor_line, thread,
        on_submit=on_submit, on_resolve=on_resolve,
    )

    def on_result(result: CommentResult) -> None:
        if thread:
            self.state.mark_read(thread.id)
        self._refresh()

    self.push_screen(screen, on_result)
```

- [ ] **Step 3: Remove old CommentScreen class from app.py (lines 142-216)**

Delete the old `CommentScreen` class. It's fully replaced by `comment_screen.py`.

- [ ] **Step 4: Manual test**

Run `revspec` on a test file. Press `c` on a line — should get the new popup:
- New thread: green border, INSERT mode, type and Tab to send
- After send: message appears in conversation, textarea cleared, mode switches to normal
- Press `i` or `c` to type again
- Press `r` to resolve — popup closes, cursor advances to next thread
- Press `q` or `Esc` to cancel

- [ ] **Step 5: Commit**

```bash
git add revspec_tui/comment_screen.py revspec_tui/app.py
git commit -m "feat: overhaul thread popup with vim modes, persistence, resolve toggle"
```

---

## Chunk 3: Rendering Improvements (Batch 3)

### Task 5: Code-block-aware rendering fix

**Files:**
- Modify: `revspec_tui/app.py` (SpecPager._line_style)

**TS ref:** `pager.ts:204-217`

- [ ] **Step 1: Fix _line_style to use green for code block content**

```python
def _line_style(self, line: str, in_code_block: bool, is_cursor: bool) -> Style:
    bg = THEME["panel"] if is_cursor else None
    stripped = line.strip()

    # Fence line (``` markers) — always dim
    if stripped.startswith("```"):
        return Style(color=THEME["text_dim"], bgcolor=bg)

    # Inside code block — green, no markdown parsing
    if in_code_block:
        return Style(color=THEME["green"], bgcolor=bg)

    # Normal markdown line styling
    if stripped.startswith("# "):
        return Style(color=THEME["blue"], bold=True, bgcolor=bg)
    elif stripped.startswith("## "):
        return Style(color=THEME["mauve"], bold=True, bgcolor=bg)
    elif stripped.startswith("### "):
        return Style(color=THEME["green"], bold=True, bgcolor=bg)
    elif stripped.startswith("- ") or stripped.startswith("* "):
        return Style(color=THEME["text"], bgcolor=bg)
    elif stripped.startswith("> "):
        return Style(color=THEME["text_muted"], italic=True, bgcolor=bg)
    else:
        return Style(color=THEME["text"], bgcolor=bg)
```

- [ ] **Step 2: Commit**

```bash
git add revspec_tui/app.py
git commit -m "fix: code blocks render green, fence lines dim"
```

---

### Task 6: Markdown table rendering

**Files:**
- Create: `revspec_tui/markdown.py`
- Modify: `revspec_tui/app.py` (SpecPager.render)

**TS ref:** `markdown.ts:162-292`, `pager.ts:130-234`

- [ ] **Step 1: Create markdown.py with table parsing + rendering**

```python
# revspec_tui/markdown.py
"""Markdown table parsing and rendering — port of ui/markdown.ts table functions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from rich.text import Text
from rich.style import Style

from .theme import THEME

SEPARATOR_RE = re.compile(r"^\|[\s:]*-+[\s:]*(\|[\s:]*-+[\s:]*)*\|?\s*$")

# Inline markdown stripping for display width calculation
_INLINE_MD_RE = re.compile(
    r"\*\*\*(.+?)\*\*\*"
    r"|\*\*(.+?)\*\*"
    r"|\*(.+?)\*"
    r"|__(.+?)__"
    r"|_(.+?)_"
    r"|~~(.+?)~~"
    r"|\[([^\]]+)\]\([^)]+\)"
    r"|`([^`]+)`"
)


def display_width(s: str) -> int:
    """Width of text after stripping inline markdown markers."""
    def _repl(m):
        for g in m.groups():
            if g is not None:
                return g
        return m.group(0)
    return len(_INLINE_MD_RE.sub(_repl, s))


@dataclass
class TableBlock:
    start_index: int
    lines: list[str]
    separator_index: int  # relative to start, -1 if none
    col_widths: list[int]


def collect_table(spec_lines: list[str], start: int) -> TableBlock:
    """Scan from a starting | line and collect the full table block."""
    lines: list[str] = []
    i = start
    while i < len(spec_lines) and spec_lines[i].lstrip().startswith("|"):
        lines.append(spec_lines[i])
        i += 1

    # Find separator row
    separator_index = -1
    for j, line in enumerate(lines):
        if SEPARATOR_RE.match(line):
            separator_index = j
            break

    # Calculate column widths from non-separator rows
    all_cells = [
        parse_table_cells(line)
        for j, line in enumerate(lines) if j != separator_index
    ]
    max_cols = max((len(row) for row in all_cells), default=0)
    col_widths = [0] * max_cols
    for row in all_cells:
        for c, cell in enumerate(row):
            col_widths[c] = max(col_widths[c], display_width(cell))
    # Minimum width 3 per column
    col_widths = [max(w, 3) for w in col_widths]

    return TableBlock(start, lines, separator_index, col_widths)


def parse_table_cells(line: str) -> list[str]:
    """Split a table row into trimmed cell values."""
    trimmed = line.strip()
    inner = trimmed[1:] if trimmed.startswith("|") else trimmed
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def scan_table_blocks(spec_lines: list[str]) -> dict[int, TableBlock]:
    """Pre-scan all table blocks, skipping lines inside code blocks."""
    blocks: dict[int, TableBlock] = {}
    in_code = False
    i = 0
    while i < len(spec_lines):
        if spec_lines[i].lstrip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        if spec_lines[i].lstrip().startswith("|") and i not in blocks:
            block = collect_table(spec_lines, i)
            for j in range(len(block.lines)):
                blocks[i + j] = block
            i += len(block.lines)
        else:
            i += 1
    return blocks


def render_table_border(text: Text, col_widths: list[int], position: str) -> None:
    """Append a top or bottom table border to Rich Text."""
    if position == "top":
        left, mid, right = "\u250c", "\u252c", "\u2510"
    else:
        left, mid, right = "\u2514", "\u2534", "\u2518"
    parts = ["\u2500" * (w + 2) for w in col_widths]
    text.append(left + mid.join(parts) + right, Style(color=THEME["text_dim"]))


def render_table_separator(text: Text, col_widths: list[int]) -> None:
    """Append a table separator row (├─┼─┤) to Rich Text."""
    parts = ["\u2500" * (w + 2) for w in col_widths]
    text.append(
        "\u251c" + "\u253c".join(parts) + "\u2524",
        Style(color=THEME["text_dim"]),
    )


def render_table_row(text: Text, cells: list[str], col_widths: list[int], is_header: bool) -> None:
    """Append a table data/header row with padded cells to Rich Text."""
    style = Style(color=THEME["text"], bold=is_header)
    dim = Style(color=THEME["text_dim"])
    for c, width in enumerate(col_widths):
        cell_text = cells[c] if c < len(cells) else ""
        dw = display_width(cell_text)
        padding = max(0, width - dw)
        # Left border
        border = "\u2502 " if c == 0 else " \u2502 "
        text.append(border, dim)
        text.append(cell_text, style)
        if padding > 0:
            text.append(" " * padding)
    # Right border
    text.append(" \u2502", dim)


def count_extra_visual_lines(
    spec_lines: list[str],
    cursor_index: int,
    wrap_width: int = 0,
) -> int:
    """Count extra visual lines (table borders + word wrap) before cursor.
    Used to map spec line to actual visual row. Port of pager.ts:284-318."""
    num_width = max(len(str(len(spec_lines))), 3)
    gutter_width = 2 + num_width + 2
    content_width = wrap_width - gutter_width if wrap_width > gutter_width else 0

    extra = 0
    i = 0
    in_code = False
    while i < len(spec_lines):
        if spec_lines[i].lstrip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if not in_code and spec_lines[i].lstrip().startswith("|"):
            table_start = i
            while i < len(spec_lines) and spec_lines[i].lstrip().startswith("|"):
                i += 1
            table_end = i
            if cursor_index >= table_start:
                extra += 1  # top border
            if cursor_index >= table_end:
                extra += 1  # bottom border
            continue
        # Word wrap extra lines
        if not in_code and content_width > 0 and i < cursor_index:
            line_len = len(spec_lines[i])
            if line_len > content_width:
                # Estimate wrapped line count
                extra += (line_len // content_width)
        i += 1
    return extra
```

- [ ] **Step 2: Integrate table rendering into SpecPager.render()**

In `SpecPager.__init__`, add:
```python
self._table_blocks: dict[int, TableBlock] | None = None
```

In `SpecPager.render()`, before the line loop, add table block scanning:
```python
from .markdown import scan_table_blocks, render_table_border, render_table_separator, render_table_row, parse_table_cells, TableBlock

# Cache table blocks (recomputed when lines change)
if self._table_blocks is None:
    self._table_blocks = scan_table_blocks(lines)
```

Inside the line loop, before the content rendering, check for table context and render borders/rows accordingly. (See TS `pager.ts:176-234` for exact logic.)

- [ ] **Step 3: Add cache invalidation**

In `RevspecApp._refresh()`, after `state.reset()` calls, set `self.pager_widget._table_blocks = None`.

Also in `__init__`, after replaying JSONL events, set it.

- [ ] **Step 4: Manual test with a markdown file containing tables**

Create a test.md with a table and verify box-drawing borders render correctly.

- [ ] **Step 5: Commit**

```bash
git add revspec_tui/markdown.py revspec_tui/app.py
git commit -m "feat: markdown table rendering with box-drawing borders"
```

---

### Task 7: Incremental search preview

**Files:**
- Modify: `revspec_tui/app.py` (SearchScreen, _open_search)

**TS ref:** `search.ts:77-83`

- [ ] **Step 1: Add on_preview callback to SearchScreen**

Add `on_preview` parameter to `SearchScreen.__init__`. On `Input.Changed` (not just submit), if len >= 3, call `on_preview(query)`, else `on_preview(None)`.

```python
class SearchScreen(ModalScreen[tuple[str, int] | None]):
    def __init__(self, spec_lines, cursor_line, on_preview=None, **kwargs):
        super().__init__(**kwargs)
        self.spec_lines = spec_lines
        self.start_line = cursor_line
        self._on_preview = on_preview

    # Add handler:
    def on_input_changed(self, event: Input.Changed) -> None:
        if self._on_preview:
            raw = event.value.strip()
            self._on_preview(raw if len(raw) >= 3 else None)
```

- [ ] **Step 2: Wire preview callback in _open_search**

```python
def _open_search(self) -> None:
    def on_preview(query: str | None) -> None:
        if query:
            self.search_query = query
        else:
            self.search_query = None
        self._refresh()

    screen = SearchScreen(self.state.spec_lines, self.state.cursor_line, on_preview=on_preview)
    # ... rest unchanged
```

- [ ] **Step 3: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: incremental search preview (highlights update as you type)"
```

---

### Task 8: Line wrapping (:wrap toggle)

**Files:**
- Modify: `revspec_tui/app.py` (RevspecApp, SpecPager, _process_command)

**TS ref:** `pager.ts:61-117`, `app.ts:112-115`

- [ ] **Step 1: Add wrap state to RevspecApp**

```python
self._wrap_enabled = False
```

- [ ] **Step 2: Implement wrapping in SpecPager.render()**

When `wrap_width > 0`, if a line exceeds content width, split at word boundaries and render continuation lines with blank gutter.

Pass `wrap_width` from app to pager via a reactive property or method call.

- [ ] **Step 3: Fix :wrap command**

In `_process_command`, replace the stub:

```python
elif cmd == "wrap":
    self._wrap_enabled = not self._wrap_enabled
    if self.pager_widget:
        self.pager_widget.wrap_width = self.size.width if self._wrap_enabled else 0
    self._refresh()
    self._show_transient(f"Line wrap {'on' if self._wrap_enabled else 'off'}")
```

- [ ] **Step 4: Update H/M/L and zz to account for extra visual lines**

Use `count_extra_visual_lines` from `markdown.py` when wrap is enabled.

- [ ] **Step 5: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: :wrap toggle with word wrapping and visual-row mapping"
```

---

## Chunk 4: Status Bar, Thread List, Help (Batch 4)

### Task 9: Transient message icons + timer fix

**Files:**
- Modify: `revspec_tui/app.py` (_show_transient, _bottom_bar_text)

**TS ref:** `status-bar.ts:81-112`

- [ ] **Step 1: Add icon parameter and timer tracking**

```python
# In __init__:
self._message_timer = None

def _show_transient(self, message: str, icon: str | None = None, duration: float = 1.5) -> None:
    # Cancel previous timer
    if self._message_timer is not None:
        self._message_timer.stop()
    text = self._bottom_bar_text(message, icon)
    self.query_one("#bottom-bar", Static).update(text)
    self._message_timer = self.set_timer(duration, self._clear_transient)

def _clear_transient(self) -> None:
    self._message_timer = None
    self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())
    # Re-render to pick up thread preview
    self._refresh()
```

Update `_bottom_bar_text` to accept icon:

```python
def _bottom_bar_text(self, message: str | None = None, icon: str | None = None) -> Text:
    text = Text()
    if message:
        if icon == "info":
            text.append(" - ", Style(color=THEME["blue"]))
        elif icon == "warn":
            text.append(" ! ", Style(color=THEME["yellow"]))
        elif icon == "success":
            text.append(" * ", Style(color=THEME["green"]))
        text.append(message, Style(color=THEME["text_muted"]))
    else:
        # ... existing position/hints code
    return text
```

- [ ] **Step 2: Update all _show_transient calls to use icons where appropriate**

Grep for `_show_transient` and add icons matching TS behavior:
- Wrap messages → `"info"`
- Resolve success → `"success"`
- No threads / no search → no icon
- :q! warning → `"warn"`

- [ ] **Step 3: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: transient message icons (info/warn/success) with proper timer management"
```

---

### Task 10: Thread preview in bottom bar

**Files:**
- Modify: `revspec_tui/app.py` (_bottom_bar_text, _refresh)

**TS ref:** `app.ts:131-141`

- [ ] **Step 1: Add thread preview to _bottom_bar_text when no transient message**

In `_bottom_bar_text`, when `message` is None:

```python
# Check for thread on current line
thread = self.state.thread_at_line(self.state.cursor_line)
if thread and thread.messages and self._message_timer is None:
    first = thread.messages[0].text.replace("\n", " ")
    preview = first[:59] + "\u2026" if len(first) > 60 else first
    replies = len(thread.messages) - 1
    reply_str = f" ({replies} {'reply' if replies == 1 else 'replies'})" if replies > 0 else ""
    text.append(f" {preview}{reply_str} [{thread.status}]", Style(color=THEME["text_muted"]))
else:
    # Original position + hints rendering
    ...
```

- [ ] **Step 2: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: thread preview in bottom bar when cursor is on thread line"
```

---

### Task 11: Unread indicator polish + spec mutation guard + top bar fix

**Files:**
- Modify: `revspec_tui/app.py` (SpecPager.render gutter, _top_bar_text, __init__)

- [ ] **Step 1: Fix gutter indicator for pending+read threads**

In `SpecPager.render()`, replace the pending indicator logic:

```python
if thread:
    if self.state.is_unread(thread.id):
        icon = "\u2588"  # █ full block — unread
        gutter_style = Style(color=THEME["yellow"], bold=True)
    elif thread.status == "resolved":
        icon = "="
        gutter_style = Style(color=THEME["green"])
    else:
        # open or pending+read — same indicator
        icon = "\u258c"  # ▌ half block
        gutter_style = Style(color=THEME["blue"])
    text.append(icon, gutter_style)
```

- [ ] **Step 2: Add spec mutation guard**

In `__init__`:
```python
self._spec_mtime = Path(spec_file).stat().st_mtime
self._spec_mtime_changed = False
```

In `_refresh`:
```python
try:
    current_mtime = Path(self.spec_file).stat().st_mtime
    if current_mtime != self._spec_mtime:
        self._spec_mtime_changed = True
except OSError:
    pass
```

- [ ] **Step 3: Fix top bar format to match TS**

Rewrite `_top_bar_text` to match `status-bar.ts:21-79`:

```python
def _top_bar_text(self) -> Text:
    text = Text()
    name = Path(self.spec_file).name
    text.append(f" {name}", Style(color=THEME["text"], bold=True))

    if self.state.threads:
        resolved = sum(1 for t in self.state.threads if t.status == "resolved")
        total = len(self.state.threads)
        color = THEME["green"] if resolved == total else THEME["yellow"]
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(f"{resolved}/{total} resolved", Style(color=color))

    if self.state.unread_count > 0:
        n = self.state.unread_count
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(
            f"{n} new {'reply' if n == 1 else 'replies'}",
            Style(color=THEME["yellow"], bold=True),
        )

    if self._spec_mtime_changed:
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append("!! Spec changed externally", Style(color=THEME["red"], bold=True))

    # Position
    cur = self.state.cursor_line
    total = self.state.line_count
    if cur <= 1:
        pos_label = "Top"
    elif cur >= total:
        pos_label = "Bot"
    else:
        pos_label = f"{round((cur - 1) / max(1, total - 1) * 100)}%"
    text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
    text.append(f"L{cur}/{total} {pos_label}", Style(color=THEME["text_muted"]))

    # Section breadcrumb
    for i in range(cur - 1, -1, -1):
        line = self.state.spec_lines[i]
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m:
            text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
            text.append(m.group(2).strip(), Style(color=THEME["text_dim"], italic=True))
            break

    return text
```

- [ ] **Step 4: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: fix gutter indicators, add mutation guard, fix top bar format"
```

---

### Task 12: Thread list sort + filter + help screen update

**Files:**
- Modify: `revspec_tui/app.py` (ThreadListScreen, HelpScreen)

**TS ref:** `thread-list.ts:38-72`, `thread-list.ts:167-182`, `help.ts:72-121`

- [ ] **Step 1: Add sort and filter to ThreadListScreen**

Add to `__init__`:
```python
self._filter_mode = "all"  # "all" | "active" | "resolved"
self._all_threads = [t for t in threads if t.status in ("open", "pending", "resolved")]
```

Add sort method:
```python
STATUS_ORDER = {"open": 0, "pending": 1, "resolved": 2}

def _filtered_sorted(self) -> list[Thread]:
    if self._filter_mode == "active":
        filtered = [t for t in self._all_threads if t.status in ("open", "pending")]
    elif self._filter_mode == "resolved":
        filtered = [t for t in self._all_threads if t.status == "resolved"]
    else:
        filtered = self._all_threads
    return sorted(filtered, key=lambda t: (self.STATUS_ORDER.get(t.status, 3), t.line))
```

Add `q` and `ctrl+f` to `on_key`:
```python
elif event.key == "q":
    event.prevent_default()
    self.dismiss(None)
elif event.key == "ctrl+f":
    event.prevent_default()
    cycle = ["all", "active", "resolved"]
    idx = (cycle.index(self._filter_mode) + 1) % 3
    self._filter_mode = cycle[idx]
    self._rebuild_list()
```

- [ ] **Step 2: Update HelpScreen content**

Replace the hardcoded help text with the full reference from `help.ts:72-121`:

```python
help_text = """\
[bold #89b4fa]revspec — keyboard reference[/]

[bold]Quick Start[/]
  Navigate to a line and press c to comment.
  The AI replies in real-time via the thread popup.
  Press r to resolve, S to submit for rewrite.
  Press A to approve when done.

[bold]Thread Popup[/]
  New thread: INSERT mode (green border) — type and Tab to send.
  Existing thread: NORMAL mode (blue border) — scroll conversation,
  c to reply, r to resolve, q/Esc to close.

[bold]Navigation[/]
  j/k          Down/up
  gg/G         Top/bottom
  Ctrl+D/U     Half page down/up
  zz           Center cursor line
  /            Search (smartcase)
  n/N          Next/prev match
  Esc          Clear search
  ]t/[t        Next/prev thread
  ]r/[r        Next/prev unread
  ]1/[1        Next/prev h1 heading
  ]2/[2        Next/prev h2 heading
  ]3/[3        Next/prev h3 heading
  Ctrl+O/I     Jump list back/forward
  ''           Jump to previous position
  H/M/L        Screen top/middle/bottom

[bold]Review[/]
  c            Comment / view thread
  r            Resolve thread (toggle)
  R            Resolve all pending
  dd           Delete thread
  t            List threads (Ctrl+F to filter)
  S            Submit for rewrite
  A            Approve spec

[bold]Commands[/]
  :q/:wq       Quit (warns if unresolved)
  :q!          Force quit
  :{N}         Jump to line N
  :wrap        Toggle line wrapping
  Ctrl+C       Force quit

[bold]Press q or Esc to close[/]
"""
```

Also add `q` to HelpScreen dismiss (in addition to `escape`):
```python
if event.key in ("escape", "q", "question_mark"):
```

- [ ] **Step 3: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: thread list sort/filter/q-dismiss, comprehensive help screen"
```

---

## Chunk 5: CLI Subcommands + Submit Flow (Batch 5)

### Task 13: Reply CLI subcommand

**Files:**
- Create: `revspec_tui/reply.py`
- Modify: `revspec_tui/cli.py`

**TS ref:** `reply.ts`

- [ ] **Step 1: Create reply.py**

```python
# revspec_tui/reply.py
"""revspec reply — CLI subcommand for AI to reply to threads."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .protocol import LiveEvent, append_event, read_events


def run_reply(spec_file: str, thread_id: str, text: str) -> None:
    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    if not text or not text.strip():
        print("Error: Reply text cannot be empty", file=sys.stderr)
        sys.exit(1)

    jsonl_path = str(spec_path.parent / (spec_path.stem + ".review.jsonl"))
    if not Path(jsonl_path).exists():
        print(f"Error: JSONL file not found: {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    # Validate thread ID exists
    events, _ = read_events(jsonl_path)
    if not any(e.thread_id == thread_id for e in events):
        print(f"Error: Thread ID not found: {thread_id}", file=sys.stderr)
        sys.exit(1)

    # Clean shell escaping artifacts
    clean_text = text.replace("\\!", "!")

    append_event(jsonl_path, LiveEvent(
        type="reply", thread_id=thread_id,
        author="owner", text=clean_text,
        ts=int(time.time() * 1000),
    ))
```

- [ ] **Step 2: Add routing to cli.py**

```python
def main() -> None:
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("Usage: revspec <file.md>")
        print("       revspec watch <file.md>")
        print("       revspec reply <file.md> <threadId> \"<text>\"")
        sys.exit(0)

    if "--version" in args or "-v" in args:
        from importlib.metadata import version
        print(f"revspec {version('revspec')}")
        sys.exit(0)

    # Subcommand routing
    if args[0] == "reply":
        if len(args) < 4:
            print("Usage: revspec reply <file.md> <threadId> \"<text>\"", file=sys.stderr)
            sys.exit(1)
        from revspec_tui.reply import run_reply
        run_reply(args[1], args[2], args[3])
        return

    if args[0] == "watch":
        if len(args) < 2:
            print("Usage: revspec watch <file.md>", file=sys.stderr)
            sys.exit(1)
        from revspec_tui.watch import run_watch
        run_watch(args[1])
        return

    # Default: launch TUI
    spec_file = next((a for a in args if not a.startswith("--")), None)
    # ... rest unchanged
```

- [ ] **Step 3: Commit**

```bash
git add revspec_tui/reply.py revspec_tui/cli.py
git commit -m "feat: revspec reply CLI subcommand"
```

---

### Task 14: Watch CLI subcommand

**Files:**
- Create: `revspec_tui/watch.py`

**TS ref:** `watch.ts` (entire file)

- [ ] **Step 1: Create watch.py**

This is a large file. Port the full `watch.ts` behavior:
- Lock file with PID-based stale detection
- Offset file tracking
- Polling loop (500ms)
- Event processing with priority: approve > submit > session-end
- Crash recovery for unprocessed submits
- `REVSPEC_WATCH_NO_BLOCK` env var support
- Output formatting: `formatWatchOutput` and `formatSubmitOutput`

```python
# revspec_tui/watch.py
"""revspec watch — CLI subcommand for AI to monitor review events."""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from .protocol import LiveEvent, read_events, replay_events_to_threads


def run_watch(spec_file: str) -> None:
    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    jsonl_path = spec_path.parent / (spec_path.stem + ".review.jsonl")
    offset_path = spec_path.parent / (spec_path.stem + ".review.offset")
    lock_path = spec_path.parent / (spec_path.stem + ".review.lock")

    # Handle lock file
    _acquire_lock(lock_path)

    # Read offset and last submit ts
    offset, last_submit_ts = _read_offset(offset_path)

    spec_lines = spec_path.read_text(encoding="utf-8").split("\n")

    no_block = os.environ.get("REVSPEC_WATCH_NO_BLOCK") == "1"

    if no_block:
        result = _process_new_events(
            str(jsonl_path), str(offset_path), str(spec_path),
            spec_lines, offset, last_submit_ts, check_recovery=True,
        )
        if result.approved:
            print("Review approved.")
            _cleanup(lock_path, offset_path)
        elif result.output:
            sys.stdout.write(result.output)
        return

    # Blocking mode: poll until events arrive
    first_poll = True
    try:
        while True:
            result = _process_new_events(
                str(jsonl_path), str(offset_path), str(spec_path),
                spec_lines, offset, last_submit_ts, check_recovery=first_poll,
            )
            first_poll = False

            if result.approved:
                print("Review approved.")
                _cleanup(lock_path, offset_path)
                return

            if result.output:
                sys.stdout.write(result.output)
                return

            offset = result.new_offset
            # Re-read submit ts from offset file
            _, last_submit_ts = _read_offset(offset_path)

            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _release_lock(lock_path)


# --- Internal helpers ---

class _ProcessResult:
    __slots__ = ("approved", "output", "new_offset")
    def __init__(self, approved=False, output="", new_offset=0):
        self.approved = approved
        self.output = output
        self.new_offset = new_offset


def _process_new_events(
    jsonl_path: str, offset_path: str, spec_path: str,
    spec_lines: list[str], offset: int, last_submit_ts: int,
    check_recovery: bool,
) -> _ProcessResult:
    if not os.path.exists(jsonl_path):
        return _ProcessResult(new_offset=offset)

    events, new_offset = read_events(jsonl_path, offset)

    # Crash recovery
    if not events and check_recovery:
        all_events, _ = read_events(jsonl_path, 0)
        last_submit_idx = _find_last_index(all_events, lambda e: e.type == "submit")
        if last_submit_idx >= 0:
            last_submit_event = all_events[last_submit_idx]
            if last_submit_event.ts == last_submit_ts:
                return _ProcessResult(new_offset=offset)
            after = all_events[last_submit_idx + 1:]
            has_new = any(e.type in ("comment", "reply", "approve", "session-end") for e in after)
            if not has_new:
                round_start = _find_current_round_start(all_events)
                round_threads = replay_events_to_threads(all_events[round_start:])
                resolved = [t for t in round_threads if t.status == "resolved"]
                output = _format_submit_output(resolved, spec_path)
                _write_offset(offset_path, offset, last_submit_event.ts)
                return _ProcessResult(output=output, new_offset=offset)
        return _ProcessResult(new_offset=offset)

    if not events:
        return _ProcessResult(new_offset=offset)

    _write_offset(offset_path, new_offset, last_submit_ts)

    # Priority: approve > submit > session-end
    if any(e.type == "approve" for e in events):
        return _ProcessResult(approved=True, new_offset=new_offset)

    submit_event = next((e for e in reversed(events) if e.type == "submit"), None)
    if submit_event:
        all_events, _ = read_events(jsonl_path, 0)
        round_start = _find_current_round_start(all_events)
        round_threads = replay_events_to_threads(all_events[round_start:])
        resolved = [t for t in round_threads if t.status == "resolved"]
        output = _format_submit_output(resolved, spec_path)
        _write_offset(offset_path, new_offset, submit_event.ts)
        return _ProcessResult(output=output, new_offset=new_offset)

    if any(e.type == "session-end" for e in events):
        return _ProcessResult(
            output="Session ended. Reviewer exited revspec.\n",
            new_offset=new_offset,
        )

    # Actionable events — comments and replies from reviewer
    actionable = [e for e in events if e.author == "reviewer" and e.type in ("comment", "reply")]
    if not actionable:
        return _ProcessResult(new_offset=new_offset)

    all_events, _ = read_events(jsonl_path, 0)
    all_threads = replay_events_to_threads(all_events)
    threads_by_id = {t.id: t for t in all_threads}

    output = _format_watch_output(actionable, threads_by_id, spec_lines, spec_path)
    return _ProcessResult(output=output, new_offset=new_offset)


def _format_watch_output(events, threads_by_id, spec_lines, spec_path):
    new_ids, reply_ids = [], []
    seen = set()
    for e in events:
        if not e.thread_id:
            continue
        if e.type == "comment" and e.thread_id not in seen:
            new_ids.append(e.thread_id)
            seen.add(e.thread_id)
        elif e.type == "reply" and e.thread_id not in reply_ids:
            reply_ids.append(e.thread_id)

    lines = []
    if new_ids:
        lines.append("=== New Comments ===")
        for tid in new_ids:
            t = threads_by_id.get(tid)
            if not t:
                continue
            lines.append(f"Thread: {tid} (line {t.line})")
            ctx = _get_context(spec_lines, t.line, 2)
            if ctx:
                lines.append("  Context:")
                lines.extend(f"    {c}" for c in ctx)
            for msg in t.messages:
                lines.append(f"  [{msg.author}]: {msg.text}")
            lines.append(f"  To reply: revspec reply {spec_path} {tid} \"<your reply>\"")
            lines.append("")

    if reply_ids:
        lines.append("=== Replies ===")
        for tid in reply_ids:
            t = threads_by_id.get(tid)
            if not t:
                continue
            lines.append(f"Thread: {tid} (line {t.line})")
            for msg in t.messages:
                lines.append(f"  [{msg.author}]: {msg.text}")
            lines.append(f"  To reply: revspec reply {spec_path} {tid} \"<your reply>\"")
            lines.append("")

    if new_ids or reply_ids:
        lines.append(f"When done replying, run: revspec watch {Path(spec_path).name}")
        lines.append("")

    return "\n".join(lines) + ("\n" if lines else "")


def _format_submit_output(resolved_threads, spec_path):
    lines = ["=== Submit: Rewrite Requested ===", ""]
    if resolved_threads:
        lines.append("Resolved threads:")
        for t in resolved_threads:
            reviewer_msgs = [m for m in t.messages if m.author == "reviewer"]
            owner_msgs = [m for m in t.messages if m.author == "owner"]
            lines.append(f"  {t.id} (line {t.line}): \"{'; '.join(m.text for m in reviewer_msgs)}\"")
            if owner_msgs:
                lines.append(f"    \u2192 AI: \"{'; '.join(m.text for m in owner_msgs)}\"")
        lines.append("")
    lines.append(f"Rewrite the spec incorporating the above, then run: revspec watch {Path(spec_path).name}")
    lines.append("")
    return "\n".join(lines)


def _get_context(spec_lines, line_number, context_size):
    idx = line_number - 1
    start = max(0, idx - context_size)
    end = min(len(spec_lines) - 1, idx + context_size)
    return [
        f"{'>' if i == idx else ' '} {i + 1}: {spec_lines[i]}"
        for i in range(start, end + 1)
    ]


def _find_current_round_start(events):
    count = 0
    for i in range(len(events) - 1, -1, -1):
        if events[i].type == "submit":
            count += 1
            if count == 2:
                return i + 1
    return 0


def _find_last_index(lst, pred):
    for i in range(len(lst) - 1, -1, -1):
        if pred(lst[i]):
            return i
    return -1


def _acquire_lock(lock_path):
    if lock_path.exists():
        try:
            locked_pid = int(lock_path.read_text().strip())
            if locked_pid != os.getpid():
                try:
                    os.kill(locked_pid, 0)
                    print(f"Error: Another revspec watch is running (PID {locked_pid})", file=sys.stderr)
                    sys.exit(3)
                except OSError:
                    lock_path.unlink()  # Stale lock
        except ValueError:
            lock_path.unlink()
    lock_path.write_text(str(os.getpid()))


def _release_lock(lock_path):
    try:
        if lock_path.exists() and lock_path.read_text().strip() == str(os.getpid()):
            lock_path.unlink()
    except OSError:
        pass


def _read_offset(offset_path):
    if not offset_path.exists():
        return 0, 0
    lines = offset_path.read_text().strip().split("\n")
    offset = int(lines[0]) if lines else 0
    submit_ts = int(lines[1]) if len(lines) > 1 else 0
    return offset, submit_ts


def _write_offset(offset_path, offset, submit_ts=0):
    tmp = str(offset_path) + ".tmp"
    content = f"{offset}\n{submit_ts}" if submit_ts else str(offset)
    Path(tmp).write_text(content)
    os.replace(tmp, str(offset_path))


def _cleanup(lock_path, offset_path):
    for p in (lock_path, offset_path):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
```

- [ ] **Step 2: Commit**

```bash
git add revspec_tui/watch.py
git commit -m "feat: revspec watch CLI subcommand with polling, lock, crash recovery"
```

---

### Task 15: Submit spinner + unresolved gate + spec reload + live watcher

**Files:**
- Modify: `revspec_tui/app.py` (_submit, __init__, on_mount)

**TS ref:** `spinner.ts`, `app.ts:770-820`, `live-watcher.ts`

- [ ] **Step 1: Add SpinnerScreen class**

Either in `revspec_tui/app.py` or a new `revspec_tui/spinner.py`:

```python
class SpinnerScreen(ModalScreen[str]):
    """Modal spinner while waiting for spec rewrite.
    Dismisses with: "cancelled", "timeout", or "reloaded" (set externally)."""
    SPINNER_FRAMES = ["|", "/", "-", "\\"]
    CSS = """
    SpinnerScreen { align: center middle; }
    #spinner-dialog {
        width: 50;
        height: 5;
        border: solid #cba6f7;
        background: #313244;
        padding: 1 2;
        content-align: center middle;
    }
    """

    def __init__(self, message: str, timeout_s: float = 120, **kwargs):
        super().__init__(**kwargs)
        self._message = message
        self._timeout_s = timeout_s
        self._frame = 0
        self._start = time.monotonic()

    def compose(self) -> ComposeResult:
        with Vertical(id="spinner-dialog"):
            yield Static(f"{self.SPINNER_FRAMES[0]} {self._message}", id="spinner-text")

    def on_mount(self) -> None:
        self.set_interval(0.08, self._tick)
        self.set_timer(self._timeout_s, self._on_timeout)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
        elapsed = int(time.monotonic() - self._start)
        self.query_one("#spinner-text", Static).update(
            f"{self.SPINNER_FRAMES[self._frame]} {self._message} ({elapsed}s)"
        )

    def _on_timeout(self) -> None:
        self.dismiss("timeout")

    def on_key(self, event: Key) -> None:
        if event.key == "ctrl+c":
            event.prevent_default()
            self.dismiss("cancelled")
```

- [ ] **Step 2: Rewrite _submit with unresolved gate + spinner + spec reload**

```python
def _submit(self) -> None:
    if not self.state.threads:
        self._show_transient("No threads to submit")
        return

    def do_submit() -> None:
        append_event(self.jsonl_path, LiveEvent(
            type="submit", author="reviewer", ts=int(time.time() * 1000),
        ))
        count = len(self.state.threads)
        spinner = SpinnerScreen(f"Submitting {count} thread{'s' if count != 1 else ''}...")

        def on_spinner_result(result: str) -> None:
            if self._spec_poll_timer:
                self._spec_poll_timer.stop()
                self._spec_poll_timer = None
            if result == "timeout":
                self._show_transient("AI did not update the spec. Press S to resubmit.", "warn", 3.0)
            # "cancelled" — user pressed Ctrl+C, just return to pager
            # "reloaded" — spec reload handled in _check_spec_reload

        self.push_screen(spinner, on_spinner_result)
        # Start polling spec mtime
        self._spec_poll_timer = self.set_interval(0.5, self._check_spec_reload)

    # Unresolved gate
    if not self.state.can_approve():
        open_c, pending = self.state.active_thread_count()
        total = open_c + pending
        screen = ConfirmScreen(
            "Unresolved Threads",
            f"{total} thread(s) still unresolved. Resolve all and continue?",
        )
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                for t in self.state.threads:
                    if t.status not in ("resolved", "outdated"):
                        append_event(self.jsonl_path, LiveEvent(
                            type="resolve", thread_id=t.id,
                            author="reviewer", ts=int(time.time() * 1000),
                        ))
                self.state.resolve_all()
                self._refresh()
                do_submit()
        self.push_screen(screen, on_confirm)
    else:
        do_submit()
```

- [ ] **Step 3: Add spec reload polling**

```python
# In __init__:
self._spec_poll_timer = None
self._live_watcher_timer = None
self._live_watcher_offset = 0

def _check_spec_reload(self) -> None:
    try:
        current_mtime = Path(self.spec_file).stat().st_mtime
        if current_mtime != self._spec_mtime:
            if self._spec_poll_timer:
                self._spec_poll_timer.stop()
                self._spec_poll_timer = None
            new_content = Path(self.spec_file).read_text(encoding="utf-8")
            self.state.reset(new_content.split("\n"))
            self._spec_mtime = current_mtime
            self._spec_mtime_changed = False
            self.search_query = None
            self._jump_list = [1]
            self._jump_index = 0
            if self.pager_widget:
                self.pager_widget._table_blocks = None
            # Dismiss spinner (self IS the app — not self.app)
            self.pop_screen()
            self._refresh()
            self._show_transient("Spec rewritten \u2014 review cleared", "success", 2.5)
    except OSError:
        pass
```

- [ ] **Step 4: Add live watcher polling**

```python
def on_mount(self) -> None:
    self._refresh()
    # Start live watcher polling
    if os.path.exists(self.jsonl_path):
        self._live_watcher_offset = os.path.getsize(self.jsonl_path)
    self._live_watcher_timer = self.set_interval(0.5, self._check_live_events)

def _check_live_events(self) -> None:
    try:
        events, new_offset = read_events(self.jsonl_path, self._live_watcher_offset)
        if events:
            self._live_watcher_offset = new_offset
            owner_events = [e for e in events if e.author == "owner"]
            last_reply_line = None
            for e in owner_events:
                if e.type == "reply" and e.thread_id and e.text:
                    self.state.add_owner_reply(e.thread_id, e.text, e.ts)
                    t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                    if t:
                        last_reply_line = t.line
            if owner_events:
                self._refresh()
                if last_reply_line:
                    self._show_transient(f"AI replied on line {last_reply_line}", "info")
    except OSError:
        pass
```

- [ ] **Step 5: Commit**

```bash
git add revspec_tui/app.py
git commit -m "feat: submit spinner, unresolved gate, spec reload, live watcher"
```

---

## Chunk 6: Tests (Batch 6)

### Task 16: Protocol unit tests

**Files:**
- Create: `tests/test_protocol.py`

- [ ] **Step 1: Write protocol tests**

```python
# tests/test_protocol.py
"""Tests for JSONL protocol."""
import json
import os
import tempfile
import pytest
from revspec_tui.protocol import (
    LiveEvent, append_event, read_events, replay_events_to_threads,
    is_valid_event, parse_event,
)


class TestAppendAndRead:
    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "test.jsonl")
        ev = LiveEvent(type="comment", author="reviewer", ts=1000,
                       thread_id="abc", line=5, text="hello")
        append_event(path, ev)
        events, offset = read_events(path)
        assert len(events) == 1
        assert events[0].type == "comment"
        assert events[0].thread_id == "abc"
        assert events[0].text == "hello"
        assert offset > 0

    def test_offset_reading(self, tmp_path):
        path = str(tmp_path / "test.jsonl")
        append_event(path, LiveEvent(type="comment", author="r", ts=1, thread_id="a", line=1, text="x"))
        _, offset1 = read_events(path)
        append_event(path, LiveEvent(type="reply", author="o", ts=2, thread_id="a", text="y"))
        events, offset2 = read_events(path, offset1)
        assert len(events) == 1
        assert events[0].type == "reply"

    def test_malformed_lines_skipped(self, tmp_path):
        path = str(tmp_path / "test.jsonl")
        with open(path, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "comment", "author": "r", "ts": 1, "threadId": "a", "line": 1, "text": "x"}) + "\n")
        events, _ = read_events(path)
        assert len(events) == 1


class TestReplay:
    def test_comment_creates_thread(self):
        events = [LiveEvent(type="comment", author="reviewer", ts=1, thread_id="t1", line=5, text="hello")]
        threads = replay_events_to_threads(events)
        assert len(threads) == 1
        assert threads[0].id == "t1"
        assert threads[0].line == 5

    def test_reply_adds_message(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1, thread_id="t1", line=5, text="hello"),
            LiveEvent(type="reply", author="owner", ts=2, thread_id="t1", text="hi back"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads[0].messages) == 2
        assert threads[0].status == "pending"

    def test_resolve_and_unresolve(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1, thread_id="t1", line=5, text="x"),
            LiveEvent(type="resolve", author="reviewer", ts=2, thread_id="t1"),
        ]
        threads = replay_events_to_threads(events)
        assert threads[0].status == "resolved"

    def test_delete_removes_thread(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1, thread_id="t1", line=5, text="x"),
            LiveEvent(type="delete", author="reviewer", ts=2, thread_id="t1"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 0
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_protocol.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_protocol.py
git commit -m "test: protocol unit tests (roundtrip, offset, replay, malformed)"
```

---

### Task 17: CLI integration tests

**Files:**
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write CLI tests**

```python
# tests/test_cli.py
"""Integration tests for CLI subcommands."""
import json
import os
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path
from revspec_tui.protocol import LiveEvent, append_event, read_events


class TestReplyCommand:
    def test_appends_reply_event(self, tmp_path):
        spec = tmp_path / "test.md"
        spec.write_text("# Test\nline 2\n")
        jsonl = tmp_path / "test.review.jsonl"
        append_event(str(jsonl), LiveEvent(
            type="comment", author="reviewer", ts=1000,
            thread_id="abc123", line=1, text="fix this",
        ))
        # Run reply via module
        from revspec_tui.reply import run_reply
        run_reply(str(spec), "abc123", "Fixed!")
        events, _ = read_events(str(jsonl))
        assert len(events) == 2
        assert events[1].type == "reply"
        assert events[1].author == "owner"
        assert events[1].text == "Fixed!"

    def test_rejects_missing_thread(self, tmp_path):
        spec = tmp_path / "test.md"
        spec.write_text("# Test\n")
        jsonl = tmp_path / "test.review.jsonl"
        append_event(str(jsonl), LiveEvent(
            type="comment", author="reviewer", ts=1000,
            thread_id="abc123", line=1, text="x",
        ))
        from revspec_tui.reply import run_reply
        with pytest.raises(SystemExit):
            run_reply(str(spec), "nonexistent", "text")


class TestWatchNonBlocking:
    def test_processes_comment(self, tmp_path, monkeypatch):
        spec = tmp_path / "test.md"
        spec.write_text("# Test\nline 2\n")
        jsonl = tmp_path / "test.review.jsonl"
        append_event(str(jsonl), LiveEvent(
            type="comment", author="reviewer", ts=1000,
            thread_id="abc123", line=1, text="fix this",
        ))
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        from revspec_tui.watch import run_watch
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            run_watch(str(spec))
        output = mock_stdout.getvalue()
        assert "New Comments" in output
        assert "abc123" in output
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: CLI integration tests for reply and watch subcommands"
```

---

### Task 18: Extended state tests

**Files:**
- Modify: `tests/test_state.py`

- [ ] **Step 1: Add comprehensive state tests**

Add test classes for: `add_comment`, `reply_to_thread`, `resolve_thread`, `delete_thread`, `thread_at_line`, `next_thread`/`prev_thread` (including wrap behavior), `next_heading`/`prev_heading`, `can_approve`, `active_thread_count`, `mark_read`/`is_unread`, `reset`.

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_state.py
git commit -m "test: comprehensive state unit tests"
```

---

## Post-Implementation Verification

After all tasks are complete:

1. **Full test suite:** `.venv/bin/python -m pytest tests/ -v` — all pass
2. **Manual smoke test:** Run `revspec <test-file.md>` and verify:
   - All keybindings work (j/k, G/gg, H/M/L, zz, Ctrl+O/I, '', ]t/[t, ]r/[r, R, dd, c, r, t, /, n/N, S, A, :q, :wrap, ?)
   - Thread popup has vim normal/insert modes
   - Tables render with box-drawing borders
   - Code blocks render green
   - Search highlighting respects smartcase
   - Incremental search preview works
   - Top bar shows resolved count, unread count, section breadcrumb
   - Bottom bar shows thread preview
3. **CLI subcommands:** `revspec reply` and `revspec watch` (with `REVSPEC_WATCH_NO_BLOCK=1`)
4. **Live watcher:** Start TUI, run `revspec reply` from another terminal, verify reply appears in TUI
