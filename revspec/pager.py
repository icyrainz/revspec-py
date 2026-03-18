"""SpecPager — scrollable line-based spec viewer using Textual's Line API."""

from __future__ import annotations

import re

from textual.scroll_view import ScrollView
from textual.reactive import reactive
from textual.strip import Strip
from textual.geometry import Size
from rich.text import Text
from rich.style import Style
from rich.console import Console

from .state import ReviewState
from .theme import THEME
from .renderer import (
    line_style, is_block_element, append_line_content,
    append_inline_styled, append_highlighted, gutter_width,
)
from .markdown import (
    scan_table_blocks, render_table_border, render_table_separator,
    render_table_row, parse_table_cells, TableBlock,
)


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
        self.show_line_numbers: bool = True
        self._visual_rows: list[tuple] = []
        self._code_state_map: dict[int, bool] = {}
        self._spec_to_visual: dict[int, int] = {}
        self._rich_console = Console(width=200, no_color=False)

    def _gutter_width(self) -> tuple[int, int]:
        return gutter_width(len(self.state.spec_lines), self.show_line_numbers)

    def invalidate_table_cache(self) -> None:
        self._table_blocks = None

    def rebuild_visual_model(self) -> None:
        """Rebuild the visual row model from spec lines."""
        lines = self.state.spec_lines
        if self._table_blocks is None:
            self._table_blocks = scan_table_blocks(lines)

        width = self.size.width if self.size.width > 0 else 200
        _, gutter_total = self._gutter_width()
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
                if content_width > 0 and len(line) > content_width:
                    extra = (len(line) - 1) // content_width
                    for seg in range(1, extra + 1):
                        rows.append(("spec_wrap", i, seg))

            i += 1

        self._visual_rows = rows
        self._code_state_map = code_state_map
        self._spec_to_visual = spec_to_vis
        self.virtual_size = Size(width, len(rows))

    def refresh_content(self) -> None:
        self.rebuild_visual_model()
        self.refresh()

    def on_mount(self) -> None:
        super().on_mount()
        self.rebuild_visual_model()

    def on_resize(self) -> None:
        self.rebuild_visual_model()

    def visual_row_for_cursor(self) -> int:
        return self._spec_to_visual.get(self.cursor_line, self.cursor_line - 1)

    def spec_line_at_visual_row(self, vis_row: int) -> int:
        if vis_row < 0:
            return 1
        if vis_row >= len(self._visual_rows):
            return self.state.line_count
        row = self._visual_rows[vis_row]
        return row[1] + 1

    def scroll_cursor_visible(self, center: bool = False) -> None:
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
        num_width, gutter_total = self._gutter_width()
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
            _kind, spec_idx, seg = row
            line = lines[spec_idx]
            line_num = spec_idx + 1
            is_cursor = line_num == self.cursor_line
            cursor_bg = THEME["panel"] if is_cursor else None
            in_code = self._code_state_map.get(spec_idx, False)

            start = seg * content_width
            end = start + content_width
            segment_text = line[start:end]

            text = Text()
            text.append(gutter_blank, Style(color=THEME["text_dim"], bgcolor=cursor_bg))
            if not in_code and line.lstrip().startswith("> "):
                text.append(
                    segment_text,
                    Style(color=THEME["text_muted"], italic=True, bgcolor=cursor_bg),
                )
            else:
                content_style = line_style(line, in_code, is_cursor)
                text.append(segment_text, content_style)
            segments = list(text.render(self._rich_console))
            return Strip(segments).crop(0, width)

        # Regular spec line
        _kind, spec_idx = row
        line = lines[spec_idx]
        line_num = spec_idx + 1
        is_cursor = line_num == self.cursor_line
        thread = self.state.thread_at_line(line_num)
        cursor_bg = THEME["panel"] if is_cursor else None
        in_code = self._code_state_map.get(spec_idx, False)

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
        if self.show_line_numbers:
            num_str = f"{line_num:>{num_width}}  "
            text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=cursor_bg))
        else:
            text.append(" ", Style(bgcolor=cursor_bg))

        # Content
        if is_table:
            if rel_idx == table_block.separator_index:
                render_table_separator(text, table_block.col_widths)
            else:
                is_header = table_block.separator_index >= 0 and rel_idx < table_block.separator_index
                cells = parse_table_cells(line)
                render_table_row(text, cells, table_block.col_widths, is_header)
        else:
            content_style = line_style(line, in_code, is_cursor)
            content = line if line else " "
            if self.wrap_width > 0 and len(content) > content_width:
                content = content[:content_width]

            if self.search_query:
                cs = self.search_query != self.search_query.lower()
                q = self.search_query if cs else self.search_query.lower()
                hay = content if cs else content.lower()
                if q in hay:
                    append_highlighted(text, content, self.search_query, content_style)
                else:
                    text.append(content, content_style)
            elif is_block_element(line, in_code):
                append_line_content(text, content, in_code, is_cursor)
            elif not in_code and not line.strip().startswith("```"):
                stripped = line.lstrip()
                heading_match = re.match(r"^(#{1,6})\s+", stripped)
                if heading_match:
                    prefix_len = heading_match.end()
                    lead_spaces = len(line) - len(stripped)
                    heading_content = content[lead_spaces + prefix_len:]
                    text.append(content[:lead_spaces + prefix_len], content_style)
                    append_inline_styled(text, heading_content, content_style)
                else:
                    append_inline_styled(text, content, content_style)
            else:
                text.append(content, content_style)

        segments = list(text.render(self._rich_console))
        return Strip(segments).crop(0, width)
