"""Textual-based TUI for revspec — prototype."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.widgets import Static, TextArea, Input, Footer, Header
from textual.reactive import reactive
from textual.message import Message as TMessage
from textual.strip import Strip
from textual.geometry import Size
from rich.text import Text
from rich.style import Style
from rich.console import Console

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
    count_extra_visual_lines, parse_inline_markdown,
)


# ---------------------------------------------------------------------------
# Pager widget — scrollable line-based spec viewer
# ---------------------------------------------------------------------------

class SpecPager(ScrollView):
    """Renders spec lines with line numbers, cursor highlight, and gutter indicators.

    Uses the Textual Line API (ScrollView) for efficient virtual scrolling.
    Each visual row is rendered on-demand via render_line().
    """

    DEFAULT_CSS = """
    SpecPager {
        overflow-y: auto;
        overflow-x: hidden;
        scrollbar-size: 0 0;
    }
    """

    # Disable inherited ScrollableContainer bindings — the App handles all keys
    BINDINGS = []

    cursor_line = reactive(1)
    search_query = reactive("")

    def __init__(self, state: ReviewState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._table_blocks: dict[int, TableBlock] | None = None
        self.wrap_width: int = 0  # 0 = no wrapping
        # Visual row model: list of tuples describing each visual row
        # Each entry: ("spec", spec_index) | ("table_border", spec_index, "top"/"bottom")
        self._visual_rows: list[tuple] = []
        # Precomputed code-block state per spec line index (state BEFORE the line)
        self._code_state_map: dict[int, bool] = {}
        # Map from spec line number (1-based) to first visual row index
        self._spec_to_visual: dict[int, int] = {}
        self._rich_console = Console(width=200, no_color=False)

    def invalidate_table_cache(self) -> None:
        self._table_blocks = None

    def rebuild_visual_model(self) -> None:
        """Rebuild the visual row model from spec lines.

        The model accounts for table border rows and wrapped continuation rows.
        Row types:
          ("spec", spec_idx)              - a spec line (or first segment if wrapped)
          ("spec_wrap", spec_idx, seg)    - continuation segment of a wrapped line
          ("table_border", spec_idx, pos) - table top/bottom border
        """
        lines = self.state.spec_lines
        if self._table_blocks is None:
            self._table_blocks = scan_table_blocks(lines)

        width = self.size.width if self.size.width > 0 else 200
        num_width = max(len(str(len(lines))), 3)
        gutter_total = 2 + num_width + 2
        content_width = width - gutter_total if self.wrap_width > 0 else 0

        rows: list[tuple] = []
        in_code = False
        code_state_map: dict[int, bool] = {}
        spec_to_vis: dict[int, int] = {}
        i = 0

        while i < len(lines):
            line = lines[i]
            table_block = self._table_blocks.get(i)
            is_table = table_block is not None and not self.search_query

            code_state_map[i] = in_code

            if line.strip().startswith("```"):
                in_code = not in_code

            if is_table:
                rel_idx = i - table_block.start_index
                if rel_idx == 0:
                    rows.append(("table_border", i, "top"))
                spec_to_vis[i + 1] = len(rows)
                rows.append(("spec", i))
                if rel_idx == len(table_block.lines) - 1:
                    rows.append(("table_border", i, "bottom"))
            else:
                spec_to_vis[i + 1] = len(rows)
                rows.append(("spec", i))
                # Add wrapped continuation rows if wrapping is enabled
                if content_width > 0 and len(line) > content_width:
                    extra = (len(line) - 1) // content_width  # number of continuation rows
                    for seg in range(1, extra + 1):
                        rows.append(("spec_wrap", i, seg))

            i += 1

        self._visual_rows = rows
        self._code_state_map = code_state_map
        self._spec_to_visual = spec_to_vis
        self.virtual_size = Size(width, len(rows))

    def refresh_content(self) -> None:
        """Call after state changes to rebuild model and redraw."""
        self.rebuild_visual_model()
        self.refresh()

    def on_mount(self) -> None:
        super().on_mount()
        self.rebuild_visual_model()

    def on_resize(self) -> None:
        self.rebuild_visual_model()

    def visual_row_for_cursor(self) -> int:
        """Get the visual row index for the current cursor line."""
        return self._spec_to_visual.get(self.cursor_line, self.cursor_line - 1)

    def spec_line_at_visual_row(self, vis_row: int) -> int:
        """Get the spec line number (1-based) at or near a visual row."""
        if vis_row < 0:
            return 1
        if vis_row >= len(self._visual_rows):
            return self.state.line_count
        row = self._visual_rows[vis_row]
        if row[0] == "spec":
            return row[1] + 1
        # For table border rows, return the associated spec line
        return row[1] + 1

    def scroll_cursor_visible(self, center: bool = False) -> None:
        """Scroll to keep the cursor line visible in the viewport."""
        vis_row = self.visual_row_for_cursor()
        view_h = self.size.height
        if view_h <= 0:
            return
        if center:
            target = max(0, vis_row - view_h // 2)
            self.scroll_to(y=target, animate=False)
        else:
            scroll_top = round(self.scroll_offset.y)
            if vis_row < scroll_top:
                self.scroll_to(y=vis_row, animate=False)
            elif vis_row >= scroll_top + view_h:
                self.scroll_to(y=vis_row - view_h + 1, animate=False)

    def render_line(self, y: int) -> Strip:
        """Render a single visual row. Called by Textual's compositor."""
        virtual_y = y + round(self.scroll_offset.y)

        if virtual_y < 0 or virtual_y >= len(self._visual_rows):
            return Strip.blank(self.size.width)

        row = self._visual_rows[virtual_y]
        lines = self.state.spec_lines
        num_width = max(len(str(len(lines))), 3)
        gutter_total = 2 + num_width + 2
        gutter_blank = " " * gutter_total
        width = self.size.width
        content_width = width - gutter_total

        if row[0] == "table_border":
            _kind, spec_idx, position = row
            table_block = self._table_blocks.get(spec_idx) if self._table_blocks else None
            text = Text()
            text.append(gutter_blank, Style(color=THEME["text_dim"]))
            if table_block:
                render_table_border(text, table_block.col_widths, position)
            segments = list(text.render(self._rich_console))
            return Strip(segments).crop(0, width)

        if row[0] == "spec_wrap":
            # Continuation segment of a wrapped line
            _kind, spec_idx, seg = row
            line = lines[spec_idx]
            line_num = spec_idx + 1
            is_cursor = line_num == self.cursor_line
            cursor_bg = THEME["panel"] if is_cursor else None
            in_code = self._code_state_map.get(spec_idx, False)

            # Extract the segment of the line for this wrap row
            start = seg * content_width
            end = start + content_width
            segment_text = line[start:end]

            text = Text()
            # Continuation rows get blank gutter with cursor bg
            text.append(gutter_blank, Style(color=THEME["text_dim"], bgcolor=cursor_bg))
            # For blockquote wrap continuations, keep italic + text_muted
            if not in_code and line.lstrip().startswith("> "):
                text.append(
                    segment_text,
                    Style(color=THEME["text_muted"], italic=True, bgcolor=cursor_bg),
                )
            else:
                content_style = self._line_style(line, in_code, is_cursor)
                text.append(segment_text, content_style)
            segments = list(text.render(self._rich_console))
            return Strip(segments).crop(0, width)

        # Regular spec line (first row, or only row if not wrapped)
        _kind, spec_idx = row
        line = lines[spec_idx]
        line_num = spec_idx + 1
        is_cursor = line_num == self.cursor_line
        thread = self.state.thread_at_line(line_num)
        cursor_bg = THEME["panel"] if is_cursor else None
        in_code = self._code_state_map.get(spec_idx, False)

        # Table context
        table_block = self._table_blocks.get(spec_idx) if self._table_blocks else None
        is_table = table_block is not None and not self.search_query
        rel_idx = spec_idx - table_block.start_index if is_table else -1

        text = Text()

        # Cursor prefix
        prefix = ">" if is_cursor else " "
        prefix_color = THEME["mauve"] if is_cursor else THEME["text_dim"]
        text.append(prefix, Style(color=prefix_color, bgcolor=cursor_bg))

        # Gutter indicator
        if thread:
            if self.state.is_unread(thread.id):
                gutter_style = Style(color=THEME["yellow"], bgcolor=cursor_bg)
            elif thread.status == "resolved":
                gutter_style = Style(color=THEME["green"], bgcolor=cursor_bg)
            else:
                gutter_style = Style(color=THEME["text"], bgcolor=cursor_bg)
            text.append("\u2588", gutter_style)
        else:
            text.append(" ", Style(bgcolor=cursor_bg))

        # Line number
        num_str = f"{line_num:>{num_width}}  "
        text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=cursor_bg))

        # Content
        if is_table:
            if rel_idx == table_block.separator_index:
                render_table_separator(text, table_block.col_widths)
            else:
                is_header = table_block.separator_index >= 0 and rel_idx < table_block.separator_index
                cells = parse_table_cells(line)
                render_table_row(text, cells, table_block.col_widths, is_header)
        else:
            content_style = self._line_style(line, in_code, is_cursor)
            # When wrapping, only show first segment
            content = line if line else " "
            if self.wrap_width > 0 and len(content) > content_width:
                content = content[:content_width]

            if self.search_query:
                cs = self.search_query != self.search_query.lower()
                q = self.search_query if cs else self.search_query.lower()
                hay = content if cs else content.lower()
                if q in hay:
                    self._append_highlighted(text, content, self.search_query, content_style, is_cursor)
                else:
                    text.append(content, content_style)
            elif self._is_block_element(line, in_code):
                self._append_line_content(text, content, in_code, is_cursor)
            elif not in_code and not line.strip().startswith("```"):
                # Inline markdown for headings and regular lines
                stripped = line.lstrip()
                heading_match = re.match(r"^(#{1,6})\s+", stripped)
                if heading_match:
                    # Render heading prefix with heading style, then inline-parse content
                    prefix_len = heading_match.end()
                    lead_spaces = len(line) - len(stripped)
                    heading_content = content[lead_spaces + prefix_len:]
                    # Append the # prefix portion
                    text.append(content[:lead_spaces + prefix_len], content_style)
                    # Inline-parse the heading text
                    self._append_inline_styled(text, heading_content, content_style)
                else:
                    self._append_inline_styled(text, content, content_style)
            else:
                text.append(content, content_style)

        segments = list(text.render(self._rich_console))
        return Strip(segments).crop(0, width)

    # Regex for horizontal rules: 3+ of the same char (-, *, _) with optional spaces
    _HR_RE = re.compile(r"^(\s*[-*_]\s*){3,}$")
    # Regex for unordered list items: optional indent + marker + space + content
    _UL_RE = re.compile(r"^(\s*)([-*+])\s+(.*)")

    def _line_style(self, line: str, in_code_block: bool, is_cursor: bool) -> Style:
        bg = THEME["panel"] if is_cursor else None

        # Fence line (``` markers) — dim
        if line.strip().startswith("```"):
            return Style(color=THEME["text_dim"], bgcolor=bg)
        # Inside code block — green, no markdown parsing
        if in_code_block:
            return Style(color=THEME["green"], bgcolor=bg)

        stripped = line.lstrip()
        heading_match = re.match(r"^(#{1,6})\s+", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            color = THEME["blue"] if level <= 2 else THEME["mauve"] if level == 3 else THEME["text_muted"]
            return Style(color=color, bold=True, bgcolor=bg)
        # Blockquotes, list items, and horizontal rules are handled by
        # _append_line_content for multi-segment rendering; return default
        # style here as fallback.
        else:
            return Style(color=THEME["text"], bgcolor=bg)

    def _is_block_element(self, line: str, in_code_block: bool) -> bool:
        """Return True if line needs multi-segment rendering (blockquote, list, hr)."""
        if in_code_block or line.strip().startswith("```"):
            return False
        stripped = line.lstrip()
        if stripped.startswith("> "):
            return True
        if self._UL_RE.match(line):
            return True
        if self._HR_RE.match(line):
            return True
        return False

    def _append_line_content(
        self, text: Text, line: str, in_code_block: bool, is_cursor: bool,
    ) -> None:
        """Append styled markdown content segments to *text*.

        Handles blockquotes (│ prefix), list items (• bullet), and horizontal
        rules (─×40).  Falls back to ``_line_style`` for everything else.
        """
        bg = THEME["panel"] if is_cursor else None

        # Skip block-element handling inside code blocks / fences
        if not in_code_block and not line.strip().startswith("```"):
            stripped = line.lstrip()

            # Horizontal rule: --- / *** / ___
            if self._HR_RE.match(line):
                text.append("\u2500" * 40, Style(color=THEME["text_dim"], dim=True, bgcolor=bg))
                return

            # Blockquote: > text  →  │ <text in italic + text_muted>
            if stripped.startswith("> "):
                text.append("\u2502 ", Style(color=THEME["mauve"], bgcolor=bg))
                bq_style = Style(color=THEME["text_muted"], italic=True, bgcolor=bg)
                self._append_inline_styled(text, stripped[2:], bq_style)
                return

            # Unordered list: - / * / + item  →  • item
            ul_match = self._UL_RE.match(line)
            if ul_match:
                indent = ul_match.group(1)
                item_text = ul_match.group(3)
                text.append(indent + "\u2022 ", Style(color=THEME["yellow"], bgcolor=bg))
                item_style = Style(color=THEME["text"], bgcolor=bg)
                self._append_inline_styled(text, item_text, item_style)
                return

        # Default: single-style rendering
        style = self._line_style(line, in_code_block, is_cursor)
        text.append(line if line else " ", style)

    def _append_inline_styled(
        self, text: Text, content: str, base_style: Style,
    ) -> None:
        """Append *content* to *text*, rendering inline markdown with styles.

        Each inline markdown segment (bold, italic, code, link, etc.) is styled
        by merging the segment-specific style on top of *base_style*.  Plain
        text segments inherit *base_style* unchanged.
        """
        for seg_text, seg_kwargs in parse_inline_markdown(content):
            if seg_kwargs:
                seg_style = base_style + Style(**seg_kwargs)
                text.append(seg_text, seg_style)
            else:
                text.append(seg_text, base_style)

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
        """Incremental search — preview highlights as you type."""
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
            inp = self.query_one("#search-input", Input)
            inp.value = ""
            inp.placeholder = "No match"
            inp.styles.color = THEME["red"]

    def on_key(self, event: Key) -> None:
        if event.key in ("escape", "ctrl+c"):
            event.prevent_default()
            event.stop()
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
        width: 44%;
        height: 9;
        border: solid #cba6f7;
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
        event.prevent_default()
        event.stop()
        if event.key in ("y", "enter"):
            self.dismiss(True)
        elif event.key in ("q", "escape", "ctrl+c"):
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
        width: 56%;
        height: 50%;
        border: solid #89b4fa;
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
        background: #313244;
        color: #f5c2e7;
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

    @staticmethod
    def _preview_text(t: Thread) -> str:
        raw = t.messages[0].text.replace("\n", " ") if t.messages else ""
        return (raw[:49] + "\u2026") if len(raw) > 50 else raw

    STATUS_COLORS = {"open": THEME["text"], "pending": THEME["yellow"], "resolved": THEME["green"]}

    def _hints_text(self) -> str:
        return f"[j/k] Navigate  [Enter] Jump  [Ctrl+f] Filter: {self._filter_mode}  [q/Esc] Close"

    def _render_item(self, t: Thread) -> Text:
        icon = STATUS_ICONS.get(t.status, " ")
        color = self.STATUS_COLORS.get(t.status, THEME["text_dim"])
        preview = self._preview_text(t)
        text = Text()
        text.append(f" {icon}", Style(color=color))
        text.append(f" #{t.id} line {t.line}: {preview}")
        return text

    def compose(self) -> ComposeResult:
        with Vertical(id="thread-list-dialog"):
            yield Static(self._title_text(), id="thread-list-title")
            if self.threads:
                for i, t in enumerate(self.threads):
                    cls = "thread-item-selected" if i == 0 else "thread-item"
                    yield Static(self._render_item(t), classes=cls)
            else:
                yield Static(" No threads. Press [Esc] to close.", classes="thread-item")
            yield Static(self._hints_text(), id="thread-hints")

    async def on_key(self, event: Key) -> None:
        event.prevent_default()
        event.stop()
        if event.key in ("escape", "q", "ctrl+c"):
            self.dismiss(None)
        elif event.key == "enter":
            if self.threads:
                self.dismiss(self.threads[self.selected_idx].line)
        elif event.key in ("j", "down"):
            self._move(1)
        elif event.key in ("k", "up"):
            self._move(-1)
        elif event.key == "ctrl+f":
            idx = (self.FILTER_CYCLE.index(self._filter_mode) + 1) % 3
            self._filter_mode = self.FILTER_CYCLE[idx]
            self.threads = self._filtered_sorted()
            self.selected_idx = 0
            await self._rebuild_items()

    async def _rebuild_items(self) -> None:
        """Remove old thread items and rebuild from current filter."""
        # Remove existing thread items — must await to avoid DuplicateIds
        for widget in list(self.query(".thread-item, .thread-item-selected")):
            await widget.remove()
        # Insert new items before the hints widget
        hints = self.query_one("#thread-hints", Static)
        dialog = self.query_one("#thread-list-dialog", Vertical)
        for i, t in enumerate(self.threads):
            cls = "thread-item-selected" if i == 0 else "thread-item"
            widget = Static(self._render_item(t), classes=cls)
            dialog.mount(widget, before=hints)
        self.query_one("#thread-list-title", Static).update(self._title_text())
        self.query_one("#thread-hints", Static).update(self._hints_text())

    def _move(self, delta: int) -> None:
        if not self.threads:
            return
        old = self.selected_idx
        self.selected_idx = (self.selected_idx + delta) % len(self.threads)
        if old != self.selected_idx:
            items = list(self.query(".thread-item, .thread-item-selected"))
            if old < len(items):
                items[old].set_classes("thread-item")
            if self.selected_idx < len(items):
                items[self.selected_idx].set_classes("thread-item-selected")


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
    }
    #help-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending_g = False

    def compose(self) -> ComposeResult:
        from importlib.metadata import version as pkg_version
        try:
            ver = pkg_version("revspec")
        except Exception:
            ver = "dev"
        help_text = f"""\
[bold #89b4fa]revspec v{ver}[/]

[bold #89b4fa]Keyboard Reference[/]

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
  ]t/\\[t        Next/prev thread
  ]r/\\[r        Next/prev unread
  ]1/\\[1        Next/prev h1 heading
  ]2/\\[2        Next/prev h2 heading
  ]3/\\[3        Next/prev h3 heading
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
  :{{N}}         Jump to line N
  :wrap        Toggle line wrapping
  Ctrl+C       Force quit

[bold]Press q or Esc to close[/]
"""
        with Vertical(id="help-dialog"):
            with VerticalScroll(id="help-scroll"):
                yield Static(help_text)

    def on_key(self, event: Key) -> None:
        event.prevent_default()
        event.stop()
        key = event.key
        if key in ("escape", "q", "question_mark", "ctrl+c"):
            self.dismiss(None)
        elif key in ("j", "down"):
            self.query_one("#help-scroll", VerticalScroll).scroll_down()
        elif key in ("k", "up"):
            self.query_one("#help-scroll", VerticalScroll).scroll_up()
        elif key == "ctrl+d":
            h = self.query_one("#help-scroll", VerticalScroll)
            h.scroll_to(y=h.scroll_offset.y + 5)
        elif key == "ctrl+u":
            h = self.query_one("#help-scroll", VerticalScroll)
            h.scroll_to(y=max(0, h.scroll_offset.y - 5))
        elif key == "g":
            if self._pending_g:
                self._pending_g = False
                self.query_one("#help-scroll", VerticalScroll).scroll_home()
            else:
                self._pending_g = True
                self.set_timer(0.3, self._clear_pending_g)
        elif key in ("shift+g", "G"):
            self._pending_g = False
            self.query_one("#help-scroll", VerticalScroll).scroll_end()

    def _clear_pending_g(self) -> None:
        self._pending_g = False


# ---------------------------------------------------------------------------
# Spinner screen — shown during submit while waiting for AI rewrite
# ---------------------------------------------------------------------------

class SpinnerScreen(ModalScreen[str]):
    """Modal spinner with elapsed time, cancellable via Ctrl+C.

    Dismiss results: "success" (spec reloaded), "cancel" (user Ctrl+C), "timeout".
    """

    SPINNER_FRAMES = ["|", "/", "-", "\\"]
    TIMEOUT_SEC = 120

    CSS = """
    SpinnerScreen { align: center middle; }
    #spinner-dialog {
        width: 50;
        height: 7;
        border: solid #cba6f7;
        background: #313244;
        padding: 1 2;
        content-align: center middle;
    }
    #spinner-text {
        text-align: center;
    }
    #spinner-hints {
        color: #6c7086;
        text-align: center;
        margin-top: 1;
    }
    """

    def __init__(self, thread_count: int, **kwargs):
        super().__init__(**kwargs)
        self._thread_count = thread_count
        self._frame = 0
        self._start_time = 0.0
        self._timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="spinner-dialog"):
            frame = self.SPINNER_FRAMES[0]
            yield Static(f"{frame} Submitting {self._thread_count} thread(s)...", id="spinner-text")
            yield Static("[Ctrl+C] Cancel", id="spinner-hints")

    def on_mount(self) -> None:
        self._start_time = time.monotonic()
        self._timer = self.set_interval(0.08, self._tick)

    def _spinner_text(self, elapsed: int) -> str:
        frame = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
        plural = "" if self._thread_count == 1 else "s"
        return f"{frame} Submitting {self._thread_count} thread{plural}...  ({elapsed}s)"

    def _tick(self) -> None:
        self._frame += 1
        elapsed = int(time.monotonic() - self._start_time)
        if elapsed >= self.TIMEOUT_SEC:
            if self._timer:
                self._timer.stop()
            self.dismiss("timeout")
            return
        self.query_one("#spinner-text", Static).update(self._spinner_text(elapsed))

    def on_key(self, event: Key) -> None:
        event.stop()
        if event.key == "ctrl+c":
            event.prevent_default()
            if self._timer:
                self._timer.stop()
            self.dismiss("cancel")


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
        height: 1fr;
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
        self._pending_key_timer: object | None = None

        # Jump list — mirrors vim :jumps (TS app.ts:161-184)
        self._jump_list: list[int] = [1]
        self._jump_index: int = 0
        self.MAX_JUMP_LIST = 50

        # Transient message timer handle
        self._message_timer = None

        # Line wrapping
        self._wrap_enabled = False

        # Spec mutation guard
        self._spec_mtime = Path(spec_file).stat().st_mtime
        self._spec_mtime_changed = False

        # Submit flow
        self._spec_poll_timer = None

        # Live watcher
        self._live_watcher_timer = None
        self._live_watcher_offset = 0

    def compose(self) -> ComposeResult:
        yield Static(self._top_bar_text(), id="top-bar")
        self.pager_widget = SpecPager(self.state, id="pager-scroll")
        yield self.pager_widget
        yield Static(self._bottom_bar_text(), id="bottom-bar")

    def on_mount(self) -> None:
        self._refresh()
        # Start live watcher polling
        if os.path.exists(self.jsonl_path):
            self._live_watcher_offset = os.path.getsize(self.jsonl_path)
        self._live_watcher_timer = self.set_interval(0.5, self._check_live_events)
        # Welcome hint on first launch
        if not self.state.threads:
            self._show_transient("Navigate to a line and press c to comment  |  ? for help", "info", 8.0)

    def _check_spec_reload(self) -> None:
        """Poll spec file mtime for reload after submit."""
        try:
            current_mtime = Path(self.spec_file).stat().st_mtime
            if current_mtime != self._spec_mtime:
                if self._spec_poll_timer:
                    self._spec_poll_timer.stop()
                    self._spec_poll_timer = None
                # Dismiss spinner if open
                if isinstance(self.screen, SpinnerScreen):
                    self.screen.dismiss("success")
                new_content = Path(self.spec_file).read_text(encoding="utf-8")
                self.state.reset(new_content.split("\n"))
                self._spec_mtime = current_mtime
                self._spec_mtime_changed = False
                self.search_query = None
                self._jump_list = [1]
                self._jump_index = 0
                if self.pager_widget:
                    self.pager_widget.invalidate_table_cache()
                # Reset live watcher offset for new round
                if os.path.exists(self.jsonl_path):
                    self._live_watcher_offset = os.path.getsize(self.jsonl_path)
                else:
                    self._live_watcher_offset = 0
                # _refresh() and transient deferred to on_spinner_done("success")
        except OSError:
            pass

    def _check_live_events(self) -> None:
        """Poll JSONL for owner events (AI replies)."""
        try:
            events, new_offset = read_events(self.jsonl_path, self._live_watcher_offset)
            self._live_watcher_offset = new_offset  # always advance
            if events:
                owner_events = [e for e in events if e.author == "owner"]
                last_reply_line = None
                last_reply_thread_id = None
                changed = False
                for e in owner_events:
                    if e.type == "reply" and e.thread_id and e.text:
                        self.state.add_owner_reply(e.thread_id, e.text, e.ts)
                        t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                        if t:
                            last_reply_line = t.line
                            last_reply_thread_id = e.thread_id
                        # Push into open CommentScreen if it's showing this thread
                        from .comment_screen import CommentScreen as CS
                        from .protocol import Message
                        active = self.screen
                        if isinstance(active, CS) and active.existing_thread and active.existing_thread.id == e.thread_id:
                            active.add_message(Message(author="owner", text=e.text, ts=e.ts))
                        changed = True
                    elif e.type == "resolve" and e.thread_id:
                        t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                        if t and t.status != "resolved":
                            t.status = "resolved"
                            changed = True
                    elif e.type == "unresolve" and e.thread_id:
                        t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                        if t and t.status == "resolved":
                            t.status = "open"
                            changed = True
                    elif e.type == "delete" and e.thread_id:
                        before = len(self.state.threads)
                        self.state.delete_thread(e.thread_id)
                        if len(self.state.threads) < before:
                            changed = True
                if changed:
                    self._refresh()
                    # Only flash if CommentScreen is not open for this thread
                    if last_reply_line:
                        from .comment_screen import CommentScreen as CS2
                        active = self.screen
                        suppress = isinstance(active, CS2) and active.existing_thread and active.existing_thread.id == last_reply_thread_id
                        if not suppress:
                            self._show_transient(f"AI replied on line {last_reply_line}", "info")
        except OSError:
            pass

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

    @staticmethod
    def _build_hints(hints: list[tuple[str, str]]) -> Text:
        """Build a styled hint bar from (key, action) pairs.

        Matches the TypeScript buildHints() format:
        - ``[key]`` in THEME["blue"]
        - ``action`` in THEME["text_muted"]
        - Double space between hint pairs
        """
        text = Text()
        text.append(" ")
        key_style = Style(color=THEME["blue"])
        action_style = Style(color=THEME["text_muted"])
        for i, (key, action) in enumerate(hints):
            text.append(f"[{key}]", key_style)
            text.append(f" {action}", action_style)
            if i < len(hints) - 1:
                text.append("  ")
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
            text.append(f" {message}", Style(color=THEME["text_muted"]))
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
                has_thread = thread is not None
                hints: list[tuple[str, str]] = [
                    ("j/k", "navigate"),
                    ("c", "comment"),
                ]
                if has_thread:
                    hints.append(("r", "resolve"))
                hints.extend([
                    ("S", "submit"),
                    ("A", "approve"),
                    ("?", "help"),
                ])
                text = self._build_hints(hints)
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
            self.pager_widget.refresh_content()
            self.pager_widget.scroll_cursor_visible()
        self.query_one("#top-bar", Static).update(self._top_bar_text())
        if self._message_timer is None:
            self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())

    def _scroll_to_cursor(self, center: bool = False) -> None:
        """Scroll the pager to keep the cursor line visible."""
        if self.pager_widget:
            self.pager_widget.scroll_cursor_visible(center=center)

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
        if len(self._jump_list) < 2:
            return
        cur = self.state.cursor_line
        if self._jump_index == 0:
            target_idx = 1
        else:
            target_idx = self._jump_index - 1
        target = self._jump_list[target_idx]
        self._jump_list[self._jump_index] = cur
        self._jump_index = target_idx
        self.state.cursor_line = min(target, self.state.line_count)
        self._refresh()

    # --- Multi-key sequence handling ---

    def _check_pending(self) -> str | None:
        """Return and clear pending key if still valid."""
        if self._pending_key and (time.monotonic() - self._pending_timer) < 0.3:
            k = self._pending_key
            self._pending_key = None
            self._cancel_pending_hint_timer()
            self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())
            return k
        self._pending_key = None
        return None

    def _cancel_pending_hint_timer(self) -> None:
        """Cancel the pending key hint timer if active."""
        if self._pending_key_timer is not None:
            self._pending_key_timer.stop()
            self._pending_key_timer = None

    def _clear_pending_hint(self) -> None:
        """Restore the bottom bar after the pending key times out."""
        self._pending_key_timer = None
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())

    def on_key(self, event: Key) -> None:
        # Skip key handling when a modal overlay is active
        if self.screen is not self.screen_stack[0]:
            return

        key = event.key

        # Check for second key of a sequence
        pending = self._check_pending()

        if pending:
            event.prevent_default()
            seq = pending + key
            if not self._handle_sequence(seq):
                # Sequence didn't match — re-process second key as standalone
                self._handle_single_key(event, key)
            return

        # Single keys that start sequences
        if key in ("g", "z", "d", "left_square_bracket", "right_square_bracket", "apostrophe"):
            event.prevent_default()
            self._start_pending(key)
            return

        # Single-key actions
        event.prevent_default()
        self._handle_single_key(event, key)

    def _start_pending(self, key: str) -> None:
        """Start a pending multi-key sequence."""
        self._pending_key = key
        self._pending_timer = time.monotonic()
        # Show pending key hint in bottom bar
        display = {"left_square_bracket": "[", "right_square_bracket": "]", "apostrophe": "'"}.get(key, key)
        self.query_one("#bottom-bar", Static).update(Text(f" {display}...", Style(color=THEME["text_dim"])))
        self._pending_key_timer = self.set_timer(0.3, self._clear_pending_hint)

    def _handle_single_key(self, event: Key, key: str) -> None:
        """Process a single key press (non-sequence)."""
        # Check if this key starts a new sequence
        if key in ("g", "z", "d", "left_square_bracket", "right_square_bracket", "apostrophe"):
            self._start_pending(key)
            return

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
                view_h = self.pager_widget.size.height if self.pager_widget else self.size.height - 2
                half = max(1, view_h // 2)
                self.state.cursor_line = min(self.state.cursor_line + half, self.state.line_count)
                self._refresh()
            case "ctrl+u":
                view_h = self.pager_widget.size.height if self.pager_widget else self.size.height - 2
                half = max(1, view_h // 2)
                self.state.cursor_line = max(self.state.cursor_line - half, 1)
                self._refresh()
            case "shift+g" | "G":
                self._push_jump()
                self.state.cursor_line = self.state.line_count
                self._refresh()
            case "ctrl+o":
                self._jump_backward()
            case "ctrl+i" | "tab":
                self._jump_forward()
            case "shift+h" | "H":
                self._push_jump()
                if self.pager_widget:
                    scroll_top = round(self.pager_widget.scroll_offset.y)
                    self.state.cursor_line = max(1, self.pager_widget.spec_line_at_visual_row(scroll_top))
                self._refresh()
            case "shift+m" | "M":
                self._push_jump()
                if self.pager_widget:
                    scroll_top = round(self.pager_widget.scroll_offset.y)
                    view_h = self.pager_widget.size.height
                    mid_row = scroll_top + view_h // 2
                    self.state.cursor_line = max(1, min(self.pager_widget.spec_line_at_visual_row(mid_row), self.state.line_count))
                self._refresh()
            case "shift+l" | "L":
                self._push_jump()
                if self.pager_widget:
                    scroll_top = round(self.pager_widget.scroll_offset.y)
                    view_h = self.pager_widget.size.height
                    bottom_row = scroll_top + view_h - 1
                    self.state.cursor_line = max(1, min(self.pager_widget.spec_line_at_visual_row(bottom_row), self.state.line_count))
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

    def _handle_sequence(self, seq: str) -> bool:
        """Handle a two-key sequence. Returns True if matched, False otherwise."""
        match seq:
            case "gg":
                self._push_jump()
                self.state.cursor_line = 1
                self._refresh()
            case "zz":
                self._scroll_to_cursor(center=True)
            case "dd":
                self._delete_thread()
            case "right_square_brackett":  # ]t
                line = self.state.next_thread()
                if line:
                    wrapped = line < self.state.cursor_line
                    self._push_jump()
                    self.state.cursor_line = line
                    self._refresh()
                    if wrapped:
                        self._show_transient("Wrapped to first thread", "info", 1.2)
                else:
                    self._show_transient("No threads")
            case "left_square_brackett":  # [t
                line = self.state.prev_thread()
                if line:
                    wrapped = line > self.state.cursor_line
                    self._push_jump()
                    self.state.cursor_line = line
                    self._refresh()
                    if wrapped:
                        self._show_transient("Wrapped to last thread", "info", 1.2)
                else:
                    self._show_transient("No threads")
            case "right_square_bracketr":  # ]r next unread
                line = self.state.next_unread_thread()
                if line:
                    self._push_jump()
                    self.state.cursor_line = line
                    self._refresh()
                else:
                    self._show_transient("No unread replies")
            case "left_square_bracketr":  # [r prev unread
                line = self.state.prev_unread_thread()
                if line:
                    self._push_jump()
                    self.state.cursor_line = line
                    self._refresh()
                else:
                    self._show_transient("No unread replies")
            case "apostropheapostrophe":  # ''
                self._jump_swap()
            case "right_square_bracket1":  # ]1
                self._jump_heading(1, forward=True)
            case "left_square_bracket1":   # [1
                self._jump_heading(1, forward=False)
            case "right_square_bracket2":  # ]2
                self._jump_heading(2, forward=True)
            case "left_square_bracket2":   # [2
                self._jump_heading(2, forward=False)
            case "right_square_bracket3":  # ]3
                self._jump_heading(3, forward=True)
            case "left_square_bracket3":   # [3
                self._jump_heading(3, forward=False)
            case _:
                return False
        return True

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
                screen.existing_thread = new_thread  # Update for live watcher identification
                screen.update_title(new_thread.id, self.state.cursor_line)
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
                # No auto-advance — popup stays open on the same thread
            self._refresh()  # Popup stays open — refresh pager underneath

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
        self._show_transient(f"{action} thread #{thread.id}", "success")

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
                self._show_transient(f"Deleted thread #{thread.id}", "success")

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
        self._refresh()  # TS silently refreshes on no match

    def _submit(self) -> None:
        if not self.state.threads:
            self._show_transient("No threads to submit.")
            return

        def do_submit() -> None:
            append_event(self.jsonl_path, LiveEvent(
                type="submit", author="reviewer", ts=int(time.time() * 1000),
            ))
            count = len(self.state.threads)
            # Start polling spec mtime for reload
            self._spec_poll_timer = self.set_interval(0.5, self._check_spec_reload)
            # Show spinner modal
            spinner = SpinnerScreen(count)

            def on_spinner_done(result: str) -> None:
                if result == "cancel":
                    # User cancelled — stop polling silently
                    if self._spec_poll_timer:
                        self._spec_poll_timer.stop()
                        self._spec_poll_timer = None
                elif result == "timeout":
                    # Timed out — stop polling and warn
                    if self._spec_poll_timer:
                        self._spec_poll_timer.stop()
                        self._spec_poll_timer = None
                    self._show_transient("AI did not update the spec. Press S to resubmit.", "warn", 3.0)
                elif result == "success":
                    self._refresh()
                    self._show_transient("Spec rewritten \u2014 review cleared", "success", 2.5)

            self.push_screen(spinner, on_spinner_done)

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
        screen = CommandScreen()

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
                self.pager_widget.invalidate_table_cache()
            self._refresh()
            self._show_transient(f"Line wrap {'on' if self._wrap_enabled else 'off'}", "info")
        else:
            try:
                line_num = int(cmd)
                if line_num <= 0:
                    self._show_transient(f"Unknown command: {cmd}", "warn")
                else:
                    self._push_jump()
                    self.state.cursor_line = min(line_num, self.state.line_count)
                    self._refresh()
            except ValueError:
                self._show_transient(f"Unknown command: {cmd}", "warn")

    def _exit_tui(self, event_type: str) -> None:
        append_event(self.jsonl_path, LiveEvent(
            type=event_type, author="reviewer", ts=int(time.time() * 1000),
        ))
        self.exit()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


class CommandScreen(ModalScreen[str | None]):
    CSS = """
    CommandScreen {
        align: left bottom;
    }
    #cmd-bar {
        width: 100%;
        height: 1;
        background: #313244;
    }
    #cmd-prefix {
        width: 1;
        color: #cdd6f4;
    }
    #cmd-input {
        width: 1fr;
        border: none;
        padding: 0;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="cmd-bar"):
            yield Static(":", id="cmd-prefix")
            yield Input(id="cmd-input")

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_key(self, event: Key) -> None:
        if event.key in ("escape", "ctrl+c"):
            event.prevent_default()
            event.stop()
            self.dismiss(None)
