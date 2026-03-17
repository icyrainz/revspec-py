"""Textual-based TUI for revspec — prototype."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea, Input, Footer, Header
from textual.reactive import reactive
from textual.message import Message as TMessage
from rich.text import Text
from rich.style import Style

from .state import ReviewState
from .protocol import (
    LiveEvent, Thread, append_event, read_events,
    replay_events_to_threads,
)
from .theme import THEME, STATUS_ICONS
from .comment_screen import CommentScreen, CommentResult
from .markdown import (
    scan_table_blocks, render_table_border, render_table_separator,
    render_table_row, parse_table_cells, TableBlock,
)


# ---------------------------------------------------------------------------
# Pager widget — scrollable line-based spec viewer
# ---------------------------------------------------------------------------

class SpecPager(Static):
    """Renders spec lines with line numbers, cursor highlight, and gutter indicators."""

    cursor_line = reactive(1)
    search_query = reactive("")

    def __init__(self, state: ReviewState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._table_blocks: dict[int, TableBlock] | None = None
        self.wrap_width: int = 0  # 0 = no wrapping

    def invalidate_table_cache(self) -> None:
        self._table_blocks = None

    def render(self) -> Text:
        lines = self.state.spec_lines
        text = Text()
        gutter_width = len(str(len(lines))) + 1
        gutter_blank = " " * (1 + 1 + gutter_width + 1)  # prefix + indicator + num + space

        # Cache table blocks
        if self._table_blocks is None:
            self._table_blocks = scan_table_blocks(lines)

        in_code_block = False
        for i, line in enumerate(lines):
            line_num = i + 1
            is_cursor = line_num == self.cursor_line
            thread = self.state.thread_at_line(line_num)

            # Table context
            table_block = self._table_blocks.get(i)
            is_table = table_block is not None and not self.search_query
            rel_idx = i - table_block.start_index if is_table else -1

            # Top border before first table row
            if is_table and rel_idx == 0:
                text.append(gutter_blank, Style(color=THEME["text_dim"]))
                render_table_border(text, table_block.col_widths, "top")
                text.append("\n")

            # Gutter indicator
            if thread:
                if self.state.is_unread(thread.id):
                    icon = "\u2588"  # █ full block — unread
                    gutter_style = Style(color=THEME["yellow"], bold=True)
                elif thread.status == "resolved":
                    icon = "="
                    gutter_style = Style(color=THEME["green"])
                else:
                    icon = "\u258c"  # ▌ half block
                    gutter_style = Style(color=THEME["blue"])
                text.append(icon, gutter_style)
            else:
                text.append(" ")

            # Line number
            num_str = f"{line_num:>{gutter_width}} "
            text.append(num_str, Style(color=THEME["text_dim"]))

            # Track code blocks
            if line.strip().startswith("```"):
                in_code_block = not in_code_block

            # Render content
            if is_table:
                # Table row rendering with box-drawing
                if rel_idx == table_block.separator_index:
                    render_table_separator(text, table_block.col_widths)
                else:
                    is_header = table_block.separator_index >= 0 and rel_idx < table_block.separator_index
                    cells = parse_table_cells(line)
                    render_table_row(text, cells, table_block.col_widths, is_header)

                # Bottom border after last row
                if rel_idx == len(table_block.lines) - 1:
                    text.append("\n")
                    text.append(gutter_blank, Style(color=THEME["text_dim"]))
                    render_table_border(text, table_block.col_widths, "bottom")
            else:
                content_style = self._line_style(line, in_code_block, is_cursor)
                content = line if line else " "

                # Search highlighting — smartcase
                if self.search_query:
                    cs = self.search_query != self.search_query.lower()
                    q = self.search_query if cs else self.search_query.lower()
                    hay = content if cs else content.lower()
                    if q in hay:
                        self._append_highlighted(text, content, self.search_query, content_style, is_cursor)
                    else:
                        text.append(content, content_style)
                else:
                    text.append(content, content_style)

            if i < len(lines) - 1:
                text.append("\n")

        return text

    def _line_style(self, line: str, in_code_block: bool, is_cursor: bool) -> Style:
        bg = THEME["panel"] if is_cursor else None

        # Fence line (``` markers) — dim
        if line.strip().startswith("```"):
            return Style(color=THEME["text_dim"], bgcolor=bg)
        # Inside code block — green, no markdown parsing
        if in_code_block:
            return Style(color=THEME["green"], bgcolor=bg)

        stripped = line.lstrip()
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

    def _append_highlighted(
        self, text: Text, content: str, query: str,
        base_style: Style, is_cursor: bool,
    ) -> None:
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




# ---------------------------------------------------------------------------
# Search modal
# ---------------------------------------------------------------------------

class SearchScreen(ModalScreen[tuple[str, int] | None]):
    """Bottom-bar search input."""

    CSS = """
    SearchScreen {
        align: left bottom;
    }
    #search-bar {
        width: 100%;
        height: 1;
        background: #313244;
    }
    #search-input {
        width: 100%;
    }
    """

    def __init__(self, spec_lines: list[str], cursor_line: int, on_preview=None, **kwargs):
        super().__init__(**kwargs)
        self.spec_lines = spec_lines
        self.start_line = cursor_line
        self._on_preview = on_preview

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-bar"):
            yield Static("/", classes="search-prefix")
            yield Input(id="search-input", placeholder="Search...")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Incremental search — preview highlights after 3+ characters."""
        if self._on_preview:
            raw = event.value.strip()
            self._on_preview(raw if len(raw) >= 3 else None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            self.dismiss(None)
            return
        match = self._find_match(query, self.start_line, 1)
        if match is not None:
            self.dismiss((query, match))
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            self.dismiss(None)

    def _find_match(self, query: str, current: int, direction: int) -> int | None:
        case_sensitive = query != query.lower()
        q = query if case_sensitive else query.lower()
        total = len(self.spec_lines)
        for offset in range(1, total + 1):
            i = (current - 1 + offset * direction) % total
            line = self.spec_lines[i] if case_sensitive else self.spec_lines[i].lower()
            if q in line:
                return i + 1
        return None


# ---------------------------------------------------------------------------
# Confirm dialog
# ---------------------------------------------------------------------------

class ConfirmScreen(ModalScreen[bool]):
    """Simple y/n confirmation."""

    CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 50;
        height: 8;
        border: solid $warning;
        background: #313244;
        padding: 1 2;
    }
    #confirm-title {
        text-style: bold;
        color: #f9e2af;
    }
    #confirm-hints {
        color: #6c7086;
        margin-top: 1;
    }
    """

    def __init__(self, title: str, message: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.message_text = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.title_text, id="confirm-title")
            yield Static(self.message_text)
            yield Static("[y/Enter] Confirm  [q/Esc] Cancel", id="confirm-hints")

    def on_key(self, event: Key) -> None:
        if event.key in ("y", "enter"):
            event.prevent_default()
            self.dismiss(True)
        elif event.key in ("n", "q", "escape"):
            event.prevent_default()
            self.dismiss(False)


# ---------------------------------------------------------------------------
# Thread list modal
# ---------------------------------------------------------------------------

class ThreadListScreen(ModalScreen[int | None]):
    """List all threads for navigation. Sorted by status, filterable with Ctrl+F."""

    STATUS_ORDER = {"open": 0, "pending": 1, "resolved": 2}
    FILTER_CYCLE = ["all", "active", "resolved"]

    CSS = """
    ThreadListScreen {
        align: center middle;
    }
    #thread-list-dialog {
        width: 70;
        height: 20;
        border: solid $accent;
        background: #313244;
        padding: 1 2;
    }
    #thread-list-title {
        text-style: bold;
        color: #89b4fa;
        margin-bottom: 1;
    }
    .thread-item {
        height: 1;
    }
    .thread-item-selected {
        height: 1;
        background: #45475a;
    }
    #thread-hints {
        color: #6c7086;
        margin-top: 1;
    }
    """

    def __init__(self, threads: list[Thread], **kwargs):
        super().__init__(**kwargs)
        self._all_threads = [t for t in threads if t.status in ("open", "pending", "resolved")]
        self._filter_mode = "all"
        self.threads = self._filtered_sorted()
        self.selected_idx = 0

    def _filtered_sorted(self) -> list[Thread]:
        if self._filter_mode == "active":
            filtered = [t for t in self._all_threads if t.status in ("open", "pending")]
        elif self._filter_mode == "resolved":
            filtered = [t for t in self._all_threads if t.status == "resolved"]
        else:
            filtered = list(self._all_threads)
        return sorted(filtered, key=lambda t: (self.STATUS_ORDER.get(t.status, 3), t.line))

    def _title_text(self) -> str:
        active = sum(1 for t in self._all_threads if t.status in ("open", "pending"))
        total = len(self._all_threads)
        return f"Threads ({active} active, {total} total) [{self._filter_mode}]"

    def compose(self) -> ComposeResult:
        with Vertical(id="thread-list-dialog"):
            yield Static(self._title_text(), id="thread-list-title")
            for i, t in enumerate(self.threads):
                icon = STATUS_ICONS.get(t.status, " ")
                preview = t.messages[0].text[:50] if t.messages else ""
                label = f" {icon} #{t.id} L{t.line}: {preview}"
                cls = "thread-item-selected" if i == 0 else "thread-item"
                yield Static(label, id=f"thread-{i}", classes=cls)
            yield Static("[j/k] Navigate  [Enter] Jump  [Ctrl+f] Filter  [q/Esc] Close", id="thread-hints")

    def on_key(self, event: Key) -> None:
        if event.key in ("escape", "q"):
            event.prevent_default()
            self.dismiss(None)
        elif event.key == "enter":
            event.prevent_default()
            if self.threads:
                self.dismiss(self.threads[self.selected_idx].line)
        elif event.key in ("j", "down"):
            event.prevent_default()
            self._move(1)
        elif event.key in ("k", "up"):
            event.prevent_default()
            self._move(-1)
        elif event.key == "ctrl+f":
            event.prevent_default()
            idx = (self.FILTER_CYCLE.index(self._filter_mode) + 1) % 3
            self._filter_mode = self.FILTER_CYCLE[idx]
            self.threads = self._filtered_sorted()
            self.selected_idx = 0
            # Rebuild display — simplest approach: dismiss and reopen
            # TODO: dynamic rebuild. For now, update title at minimum.
            self.query_one("#thread-list-title", Static).update(self._title_text())

    def _move(self, delta: int) -> None:
        if not self.threads:
            return
        old = self.selected_idx
        self.selected_idx = max(0, min(len(self.threads) - 1, self.selected_idx + delta))
        if old != self.selected_idx:
            old_widget = self.query_one(f"#thread-{old}", Static)
            new_widget = self.query_one(f"#thread-{self.selected_idx}", Static)
            old_widget.set_classes("thread-item")
            new_widget.set_classes("thread-item-selected")


# ---------------------------------------------------------------------------
# Help screen
# ---------------------------------------------------------------------------

class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-dialog {
        width: 60;
        height: 24;
        border: solid $accent;
        background: #313244;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
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
        with Vertical(id="help-dialog"):
            yield Static(help_text)

    def on_key(self, event: Key) -> None:
        if event.key in ("escape", "q", "question_mark"):
            event.prevent_default()
            self.dismiss(None)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class RevspecApp(App):
    """Textual-based revspec TUI."""

    CSS = """
    #top-bar {
        height: 1;
        background: #313244;
        color: #cdd6f4;
    }
    #pager-scroll {
        overflow-y: auto;
    }
    #bottom-bar {
        height: 1;
        background: #313244;
        color: #a6adc8;
    }
    #command-bar {
        height: 1;
        background: #313244;
        display: none;
    }
    #command-input {
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(self, spec_file: str, **kwargs):
        super().__init__(**kwargs)
        self.spec_file = spec_file
        self.spec_content = Path(spec_file).read_text(encoding="utf-8")
        spec_lines = self.spec_content.split("\n")

        self.state = ReviewState(spec_lines)
        self.pager_widget: SpecPager | None = None
        self.search_query: str | None = None

        # JSONL path
        base = Path(spec_file)
        self.jsonl_path = str(base.parent / (base.stem + ".review.jsonl"))

        # Replay existing events
        if os.path.exists(self.jsonl_path):
            events, _ = read_events(self.jsonl_path)
            for t in replay_events_to_threads(events):
                existing = next((et for et in self.state.threads if et.id == t.id), None)
                if not existing:
                    self.state.threads.append(t)
                else:
                    existing.messages = t.messages
                    existing.status = t.status

        # Multi-key sequence state
        self._pending_key: str | None = None
        self._pending_timer: float = 0

        # Jump list — mirrors vim :jumps (TS app.ts:161-184)
        self._jump_list: list[int] = [1]
        self._jump_index: int = 0
        self.MAX_JUMP_LIST = 50

        # Track scroll position for H/M/L (SpecPager extends Static, no scroll_offset)
        self._scroll_y: int = 0

        # Transient message timer handle
        self._message_timer = None

        # Line wrapping
        self._wrap_enabled = False

        # Spec mutation guard
        self._spec_mtime = Path(spec_file).stat().st_mtime
        self._spec_mtime_changed = False

    def compose(self) -> ComposeResult:
        yield Static(self._top_bar_text(), id="top-bar")
        self.pager_widget = SpecPager(self.state, id="pager-scroll")
        yield self.pager_widget
        yield Static(self._bottom_bar_text(), id="bottom-bar")

    def on_mount(self) -> None:
        self._refresh()

    def _top_bar_text(self) -> Text:
        text = Text()
        name = Path(self.spec_file).name
        text.append(f" {name}", Style(color=THEME["text"], bold=True))

        # Thread progress
        if self.state.threads:
            resolved = sum(1 for t in self.state.threads if t.status == "resolved")
            total = len(self.state.threads)
            color = THEME["green"] if resolved == total else THEME["yellow"]
            text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
            text.append(f"{resolved}/{total} resolved", Style(color=color))

        # Unread replies
        if self.state.unread_count > 0:
            n = self.state.unread_count
            text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
            text.append(
                f"{n} new {'reply' if n == 1 else 'replies'}",
                Style(color=THEME["yellow"], bold=True),
            )

        # Spec mutation guard
        if hasattr(self, "_spec_mtime_changed") and self._spec_mtime_changed:
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

    def _bottom_bar_text(self, message: str | None = None, icon: str | None = None) -> Text:
        text = Text()
        if message:
            if icon == "info":
                text.append(" - ", Style(color=THEME["blue"]))
            elif icon == "warn":
                text.append(" ! ", Style(color=THEME["yellow"]))
            elif icon == "success":
                text.append(" * ", Style(color=THEME["green"]))
            text.append(f" {message}" if not icon else message, Style(color=THEME["text_muted"]))
        else:
            # Thread preview when cursor is on a thread line
            thread = self.state.thread_at_line(self.state.cursor_line)
            if thread and thread.messages and self._message_timer is None:
                first = thread.messages[0].text.replace("\n", " ")
                preview = first[:59] + "\u2026" if len(first) > 60 else first
                replies = len(thread.messages) - 1
                reply_str = f" ({replies} {'reply' if replies == 1 else 'replies'})" if replies > 0 else ""
                text.append(f" {preview}{reply_str} [{thread.status}]", Style(color=THEME["text_muted"]))
            else:
                line = self.state.cursor_line
                total = self.state.line_count
                pct = int(line / total * 100) if total > 0 else 0
                text.append(f" L{line}/{total} ({pct}%)", Style(color=THEME["text_dim"]))
                text.append("  ", Style(color=THEME["text_dim"]))
                text.append("[c]omment [/]search [t]hreads [?]help", Style(color=THEME["text_dim"]))
        return text

    def _refresh(self) -> None:
        # Spec mutation guard
        try:
            current_mtime = Path(self.spec_file).stat().st_mtime
            if current_mtime != self._spec_mtime:
                self._spec_mtime_changed = True
        except OSError:
            pass

        if self.pager_widget:
            self.pager_widget.cursor_line = self.state.cursor_line
            if self.search_query:
                self.pager_widget.search_query = self.search_query
            else:
                self.pager_widget.search_query = ""
            self.pager_widget.update(self.pager_widget.render())
        self.query_one("#top-bar", Static).update(self._top_bar_text())
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())
        self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        if self.pager_widget:
            target = max(0, self.state.cursor_line - self.size.height // 2)
            self._scroll_y = target
            self.pager_widget.scroll_to(y=target)

    def _show_transient(self, message: str, icon: str | None = None, duration: float = 1.5) -> None:
        if self._message_timer is not None:
            self._message_timer.stop()
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text(message, icon))
        self._message_timer = self.set_timer(duration, self._clear_transient)

    def _clear_transient(self) -> None:
        self._message_timer = None
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())

    # --- Jump list ---

    def _push_jump(self) -> None:
        """Record current position in jump list before a big jump."""
        cur = self.state.cursor_line
        if self._jump_index < len(self._jump_list) - 1:
            self._jump_list[self._jump_index + 1:] = []
        if self._jump_list and self._jump_list[-1] == cur:
            return
        self._jump_list.append(cur)
        if len(self._jump_list) > self.MAX_JUMP_LIST:
            self._jump_list.pop(0)
        self._jump_index = len(self._jump_list) - 1

    def _jump_backward(self) -> None:
        """Ctrl+O — jump back in jump list."""
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

    # --- Multi-key sequence handling ---

    def _check_pending(self) -> str | None:
        """Return and clear pending key if still valid."""
        if self._pending_key and (time.monotonic() - self._pending_timer) < 0.3:
            k = self._pending_key
            self._pending_key = None
            return k
        self._pending_key = None
        return None

    def on_key(self, event: Key) -> None:
        key = event.key

        # Check for second key of a sequence
        pending = self._check_pending()

        if pending:
            event.prevent_default()
            seq = pending + key
            self._handle_sequence(seq)
            return

        # Single keys that start sequences
        if key in ("g", "z", "d", "bracketleft", "bracketright", "apostrophe"):
            event.prevent_default()
            self._pending_key = key
            self._pending_timer = time.monotonic()
            return

        # Single-key actions
        event.prevent_default()
        match key:
            case "j" | "down":
                if self.state.cursor_line < self.state.line_count:
                    self.state.cursor_line += 1
                    self._refresh()
            case "k" | "up":
                if self.state.cursor_line > 1:
                    self.state.cursor_line -= 1
                    self._refresh()
            case "ctrl+d":
                half = max(1, self.size.height // 2)
                self.state.cursor_line = min(self.state.cursor_line + half, self.state.line_count)
                self._refresh()
            case "ctrl+u":
                half = max(1, self.size.height // 2)
                self.state.cursor_line = max(self.state.cursor_line - half, 1)
                self._refresh()
            case "shift+g" | "G":
                self._push_jump()
                self.state.cursor_line = self.state.line_count
                self._refresh()
            case "ctrl+o":
                self._jump_backward()
            case "tab":
                self._jump_forward()
            case "shift+h" | "H":
                self._push_jump()
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
                    self._show_transient(f"Resolved {len(pending_threads)} pending thread(s)", "success")
            case "c":
                self._open_comment()
            case "t":
                self._open_thread_list()
            case "r":
                self._resolve_current()
            case "slash":
                self._open_search()
            case "n":
                self._search_next(1)
            case "shift+n" | "N":
                self._search_next(-1)
            case "shift+s" | "S":
                self._submit()
            case "shift+a" | "A":
                self._approve()
            case "question_mark":
                self.push_screen(HelpScreen())
            case "colon":
                self._open_command_mode()
            case "escape":
                if self.search_query:
                    self.search_query = None
                    self._refresh()
            case "ctrl+c":
                self._exit_tui("session-end")
            case _:
                pass  # ignore unmapped keys

    def _handle_sequence(self, seq: str) -> None:
        match seq:
            case "gg":
                self._push_jump()
                self.state.cursor_line = 1
                self._refresh()
            case "zz":
                if self.pager_widget:
                    half_view = max(1, self.size.height - 2) // 2
                    target = max(0, self.state.cursor_line - 1 - half_view)
                    self._scroll_y = target
                    self.pager_widget.scroll_to(y=target)
                self._refresh()
            case "dd":
                self._delete_thread()
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
            case "apostropheapostrophe":  # ''
                self._jump_swap()
            case "bracketright1":  # ]1
                self._jump_heading(1, forward=True)
            case "bracketleft1":   # [1
                self._jump_heading(1, forward=False)
            case "bracketright2":  # ]2
                self._jump_heading(2, forward=True)
            case "bracketleft2":   # [2
                self._jump_heading(2, forward=False)
            case "bracketright3":  # ]3
                self._jump_heading(3, forward=True)
            case "bracketleft3":   # [3
                self._jump_heading(3, forward=False)
            case _:
                pass

    def _jump_heading(self, level: int, forward: bool) -> None:
        line = self.state.next_heading(level) if forward else self.state.prev_heading(level)
        if line:
            self._push_jump()
            self.state.cursor_line = line
            self._refresh()
        else:
            self._show_transient(f"No h{level} headings")

    # --- Overlays ---

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

    def _open_thread_list(self) -> None:
        if not self.state.threads:
            self._show_transient("No threads")
            return
        screen = ThreadListScreen(self.state.threads)

        def on_result(line: int | None) -> None:
            if line is not None:
                self._push_jump()
                self.state.cursor_line = line
                self._refresh()

        self.push_screen(screen, on_result)

    def _resolve_current(self) -> None:
        thread = self.state.thread_at_line(self.state.cursor_line)
        if not thread:
            self._show_transient("No thread on this line")
            return
        was_resolved = thread.status == "resolved"
        self.state.resolve_thread(thread.id)
        self.state.mark_read(thread.id)
        event_type = "unresolve" if was_resolved else "resolve"
        append_event(self.jsonl_path, LiveEvent(
            type=event_type, thread_id=thread.id,
            author="reviewer", ts=int(time.time() * 1000),
        ))
        self._refresh()
        action = "Reopened" if was_resolved else "Resolved"
        self._show_transient(f"{action} thread #{thread.id}")

    def _delete_thread(self) -> None:
        thread = self.state.thread_at_line(self.state.cursor_line)
        if not thread:
            self._show_transient("No thread on this line")
            return
        screen = ConfirmScreen("Delete Thread", f"Delete thread #{thread.id} on line {thread.line}?")

        def on_result(confirmed: bool) -> None:
            if confirmed:
                self.state.delete_thread(thread.id)
                append_event(self.jsonl_path, LiveEvent(
                    type="delete", thread_id=thread.id,
                    author="reviewer", ts=int(time.time() * 1000),
                ))
                self._refresh()
                self._show_transient(f"Deleted thread #{thread.id}")

        self.push_screen(screen, on_result)

    def _open_search(self) -> None:
        def on_preview(query: str | None) -> None:
            self.search_query = query
            self._refresh()

        screen = SearchScreen(
            self.state.spec_lines, self.state.cursor_line, on_preview=on_preview,
        )

        def on_result(result: tuple[str, int] | None) -> None:
            if result:
                query, line = result
                self.search_query = query
                self._push_jump()
                self.state.cursor_line = line
            else:
                self.search_query = None
            self._refresh()

        self.push_screen(screen, on_result)

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

    def _submit(self) -> None:
        if not self.state.threads:
            self._show_transient("No threads to submit")
            return
        append_event(self.jsonl_path, LiveEvent(
            type="submit", author="reviewer", ts=int(time.time() * 1000),
        ))
        self._show_transient(f"Submitted {len(self.state.threads)} thread(s)")

    def _approve(self) -> None:
        if not self.state.can_approve():
            open_c, pending = self.state.active_thread_count()
            total = open_c + pending
            screen = ConfirmScreen(
                "Unresolved Threads",
                f"{total} thread(s) still unresolved. Resolve all and continue?",
            )

            def on_result(confirmed: bool) -> None:
                if confirmed:
                    for t in self.state.threads:
                        if t.status not in ("resolved", "outdated"):
                            append_event(self.jsonl_path, LiveEvent(
                                type="resolve", thread_id=t.id,
                                author="reviewer", ts=int(time.time() * 1000),
                            ))
                    self.state.resolve_all()
                    self._exit_tui("approve")

            self.push_screen(screen, on_result)
        else:
            self._exit_tui("approve")

    def _open_command_mode(self) -> None:
        """Simple inline command input."""
        screen = _CommandScreen(self.state)

        def on_result(cmd: str | None) -> None:
            if cmd is None:
                return
            self._process_command(cmd)

        self.push_screen(screen, on_result)

    def _process_command(self, cmd: str) -> None:
        force_quit = {"q!", "qa!", "wq!", "wqa!", "qw!", "qwa!"}
        safe_quit = {"q", "qa", "wq", "wqa", "qw", "qwa"}

        if cmd in force_quit:
            self._exit_tui("session-end")
        elif cmd in safe_quit:
            open_c, pending = self.state.active_thread_count()
            if open_c + pending > 0:
                self._show_transient(f"{open_c + pending} unresolved thread(s). Use :q! to force quit", "warn", 2.0)
            else:
                self._exit_tui("session-end")
        elif cmd == "wrap":
            self._wrap_enabled = not self._wrap_enabled
            if self.pager_widget:
                self.pager_widget.wrap_width = self.size.width if self._wrap_enabled else 0
            self._refresh()
            self._show_transient(f"Line wrap {'on' if self._wrap_enabled else 'off'}", "info")
        else:
            try:
                line_num = int(cmd)
                if 1 <= line_num <= self.state.line_count:
                    self._push_jump()
                    self.state.cursor_line = line_num
                    self._refresh()
                else:
                    self._show_transient(f"Line {line_num} out of range")
            except ValueError:
                self._show_transient(f"Unknown command: {cmd}")

    def _exit_tui(self, event_type: str) -> None:
        append_event(self.jsonl_path, LiveEvent(
            type=event_type, author="reviewer", ts=int(time.time() * 1000),
        ))
        self.exit()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


class _CommandScreen(ModalScreen[str | None]):
    CSS = """
    _CommandScreen {
        align: left bottom;
    }
    #cmd-bar {
        width: 100%;
        height: 1;
        background: #313244;
    }
    """

    def __init__(self, state: ReviewState, **kwargs):
        super().__init__(**kwargs)
        self.review_state = state

    def compose(self) -> ComposeResult:
        with Horizontal(id="cmd-bar"):
            yield Static(":")
            yield Input(id="cmd-input")

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            self.dismiss(None)
