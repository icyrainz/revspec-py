"""SpecPager — scrollable line-based spec viewer using Textual's Line API."""

from __future__ import annotations

from textual.scroll_view import ScrollView
from textual.reactive import reactive
from textual.strip import Strip
from textual.geometry import Size
from rich.text import Text
from rich.style import Style
from rich.console import Console

from bisect import bisect_left
from .state import ReviewState
from .diff_state import DiffState
from .theme import THEME, status_icon, status_color
from .renderer import (
    HEADING_RE, line_style, is_block_element, append_line_content,
    append_inline_styled, apply_search_highlight, gutter_width,
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
        self._spec_row_indices: list[int] = []
        self.diff_state: DiffState | None = None
        self._rich_console = Console(width=200, no_color=False)
        self._cached_num_width: int = 0
        self._cached_gutter_total: int = 3
        self._update_gutter_cache()

    def _is_diff_added(self, spec_idx: int) -> bool:
        """Check if spec line at 0-based index is a diff-added line."""
        ds = self.diff_state
        return ds is not None and ds.is_active and ds.is_added(spec_idx)

    def _line_bg(self, spec_idx: int, is_cursor: bool) -> str | None:
        """Resolve background color for a spec line."""
        if is_cursor:
            return THEME["panel"]
        if self._is_diff_added(spec_idx):
            return THEME["diff_added_bg"]
        in_code = self._code_state_map.get(spec_idx, False)
        is_fence = self.state.spec_lines[spec_idx].strip().startswith("```")
        if in_code or is_fence:
            return THEME["mantle"]
        return THEME["crust"]

    def _gutter_bg(self, spec_idx: int, is_cursor: bool) -> str | None:
        """Background for gutter/line-number — same as _line_bg but ignores code blocks."""
        if is_cursor:
            return THEME["panel"]
        if self._is_diff_added(spec_idx):
            return THEME["diff_added_bg"]
        return THEME["crust"]

    def _update_gutter_cache(self) -> None:
        self._cached_num_width, self._cached_gutter_total = gutter_width(
            len(self.state.spec_lines), self.show_line_numbers
        )

    @staticmethod
    def _append_ghost_rows(rows: list[tuple], removed_text: str, content_width: int, ghost_content_width: int) -> None:
        """Append diff_removed (and optional wrap) rows for a single removed line."""
        rows.append(("diff_removed", removed_text))
        if content_width > 0 and ghost_content_width > 0 and len(removed_text) > ghost_content_width:
            extra = (len(removed_text) - 1) // ghost_content_width
            for seg in range(1, extra + 1):
                rows.append(("diff_removed_wrap", removed_text, seg))

    def invalidate_table_cache(self) -> None:
        self._table_blocks = None

    def rebuild_visual_model(self) -> None:
        """Rebuild the visual row model from spec lines."""
        lines = self.state.spec_lines
        if self._table_blocks is None:
            self._table_blocks = scan_table_blocks(lines)

        self._update_gutter_cache()
        width = self.size.width if self.size.width > 0 else 200
        gutter_total = self._cached_gutter_total
        content_width = width - gutter_total if self.wrap_width > 0 else 0

        diff = self.diff_state
        diff_active = diff is not None and diff.is_active

        # Ghost row gutter width matches spec gutter for column alignment
        ghost_gutter_width = gutter_total
        ghost_content_width = width - ghost_gutter_width

        rows: list[tuple] = []
        in_code = False
        code_state_map: dict[int, bool] = {}
        spec_to_vis: dict[int, int] = {}
        spec_row_indices: list[int] = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Ghost rows BEFORE this spec line
            if diff_active:
                for removed_text in diff.removed_lines_before(i):
                    self._append_ghost_rows(rows, removed_text, content_width, ghost_content_width)

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
                spec_row_indices.append(len(rows))
                rows.append(("spec", i))
                if rel_idx == len(table_block.lines) - 1:
                    rows.append(("table_border", i, "bottom"))
            else:
                spec_to_vis[i + 1] = len(rows)
                spec_row_indices.append(len(rows))
                rows.append(("spec", i))
                if content_width > 0 and len(line) > content_width:
                    extra = (len(line) - 1) // content_width
                    for seg in range(1, extra + 1):
                        rows.append(("spec_wrap", i, seg))

            i += 1

        # Trailing removed lines after the last spec line
        if diff_active:
            for removed_text in diff.removed_lines_before(len(lines)):
                self._append_ghost_rows(rows, removed_text, content_width, ghost_content_width)

        self._visual_rows = rows
        self._code_state_map = code_state_map
        self._spec_to_visual = spec_to_vis
        self._spec_row_indices = spec_row_indices
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
        """Map visual row to spec line (1-based). Resolves ghost rows forward."""
        if vis_row < 0:
            return 1
        if vis_row >= len(self._visual_rows):
            return self.state.line_count
        row = self._visual_rows[vis_row]
        kind = row[0]
        if kind in ("spec", "spec_wrap", "table_border"):
            return row[1] + 1
        # Ghost row — resolve to next spec line via bisect
        if not self._spec_row_indices:
            return self.state.line_count
        pos = bisect_left(self._spec_row_indices, vis_row)
        if pos >= len(self._spec_row_indices):
            return self.state.line_count  # trailing ghost rows → last spec line
        spec_vis = self._spec_row_indices[pos]
        return self._visual_rows[spec_vis][1] + 1

    def scroll_cursor_visible(self, center: bool = False, margin: int = 0) -> None:
        vis_row = self.visual_row_for_cursor()
        view_h = self.size.height
        if view_h <= 0:
            return
        if center:
            target = max(0, vis_row - view_h // 2)
            self.scroll_to(y=target, animate=False)
        else:
            scroll_top = round(self.scroll_offset.y)
            scroll_bottom = scroll_top + view_h - 1
            if margin > 0 and vis_row - scroll_top < margin:
                self.scroll_to(y=max(0, vis_row - margin), animate=False)
            elif margin > 0 and scroll_bottom - vis_row < margin:
                self.scroll_to(y=vis_row - view_h + margin + 1, animate=False)
            elif vis_row < scroll_top:
                self.scroll_to(y=vis_row, animate=False)
            elif vis_row > scroll_bottom:
                self.scroll_to(y=vis_row - view_h + 1, animate=False)

    _BG_STYLE = Style(bgcolor=THEME["crust"])

    def _make_strip(self, text: Text, width: int, bg_style: Style | None = None) -> Strip:
        """Render text to strip, padding right side to full width."""
        pad = width - text.cell_len
        if pad > 0:
            text.append(" " * pad, bg_style or self._BG_STYLE)
        return Strip(list(text.render(self._rich_console))).crop(0, width)

    def render_line(self, y: int) -> Strip:
        """Render a single visual row. Called by Textual's compositor."""
        virtual_y = y + round(self.scroll_offset.y)

        if virtual_y < 0 or virtual_y >= len(self._visual_rows):
            return Strip.blank(self.size.width, self._BG_STYLE)

        row = self._visual_rows[virtual_y]
        lines = self.state.spec_lines
        num_width, gutter_total = self._cached_num_width, self._cached_gutter_total
        gutter_blank = " " * gutter_total
        width = self.size.width
        content_width = width - gutter_total

        if row[0] == "table_border":
            _kind, spec_idx, position = row
            table_block = self._table_blocks.get(spec_idx) if self._table_blocks else None
            is_cursor = (spec_idx + 1) == self.cursor_line
            border_bg = self._line_bg(spec_idx, is_cursor)
            g_bg = self._gutter_bg(spec_idx, is_cursor)
            text = Text()
            text.append(gutter_blank, Style(color=THEME["text_dim"], bgcolor=g_bg))
            if table_block:
                render_table_border(text, table_block.col_widths, position, bg=border_bg)
            return self._make_strip(text, width)

        # --- Ghost rows (diff removed) ---
        if row[0] == "diff_removed":
            removed_text = row[1]
            bg = THEME["diff_removed_bg"]
            bg_style = Style(bgcolor=bg)
            text = Text()
            # Gutter: [space][space][-][padding] — same width as spec gutter
            text.append(" ", bg_style)  # cursor column
            text.append(" ", bg_style)  # gutter icon column
            text.append("-", Style(color=THEME["red"], bgcolor=bg))
            if self.show_line_numbers:
                text.append(" " * (num_width + 1), bg_style)
            content = removed_text if removed_text else " "
            if self.wrap_width > 0:
                ghost_cw = width - gutter_total
                if ghost_cw > 0 and len(content) > ghost_cw:
                    content = content[:ghost_cw]
            text.append(content, Style(color=THEME["text_dim"], bgcolor=bg))
            return self._make_strip(text, width, bg_style)

        if row[0] == "diff_removed_wrap":
            removed_text = row[1]
            seg = row[2]
            bg = THEME["diff_removed_bg"]
            bg_style = Style(bgcolor=bg)
            ghost_cw = width - gutter_total
            start = seg * ghost_cw
            end = start + ghost_cw
            segment_text = removed_text[start:end]
            text = Text()
            text.append(" " * gutter_total, bg_style)
            text.append(segment_text, Style(color=THEME["text_dim"], bgcolor=bg))
            return self._make_strip(text, width, bg_style)

        if row[0] == "spec_wrap":
            _kind, spec_idx, seg = row
            line = lines[spec_idx]
            line_num = spec_idx + 1
            is_cursor = line_num == self.cursor_line
            in_code = self._code_state_map.get(spec_idx, False)
            is_fence = line.strip().startswith("```")
            cursor_bg = self._line_bg(spec_idx, is_cursor)

            start = seg * content_width
            end = start + content_width
            segment_text = line[start:end]

            text = Text()
            g_bg = self._gutter_bg(spec_idx, is_cursor)
            text.append(gutter_blank, Style(color=THEME["text_dim"], bgcolor=g_bg))
            if not in_code and line.lstrip().startswith("> "):
                text.append(
                    segment_text,
                    Style(color=THEME["text_muted"], italic=True, bgcolor=cursor_bg),
                )
            else:
                content_style = line_style(line, in_code, is_cursor, bg=cursor_bg)
                text.append(segment_text, content_style)
            return self._make_strip(text, width)

        # Regular spec line
        _kind, spec_idx = row
        line = lines[spec_idx]
        line_num = spec_idx + 1
        is_cursor = line_num == self.cursor_line
        thread = self.state.thread_at_line(line_num)
        in_code = self._code_state_map.get(spec_idx, False)
        is_fence = line.strip().startswith("```")
        diff_added = self._is_diff_added(spec_idx)
        cursor_bg = self._line_bg(spec_idx, is_cursor)
        g_bg = self._gutter_bg(spec_idx, is_cursor)

        table_block = self._table_blocks.get(spec_idx) if self._table_blocks else None
        is_table = table_block is not None and not self.search_query
        rel_idx = spec_idx - table_block.start_index if is_table else -1

        text = Text()

        # Cursor prefix
        prefix = ">" if is_cursor else " "
        prefix_color = THEME["mauve"] if is_cursor else THEME["text_dim"]
        text.append(prefix, Style(color=prefix_color, bgcolor=g_bg))

        # Gutter indicator
        if thread:
            color = status_color(thread.status, self.state.is_unread(thread.id))
            text.append(status_icon(thread.status), Style(color=color, bgcolor=g_bg))
        else:
            text.append(" ", Style(bgcolor=g_bg))

        # Line number (with + marker for diff-added lines)
        if self.show_line_numbers:
            if diff_added:
                num_str = f"{line_num:>{num_width}} "
                text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=g_bg))
                text.append("+", Style(color=THEME["green"], bgcolor=g_bg))
            else:
                num_str = f"{line_num:>{num_width}}  "
                text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=g_bg))
        else:
            if diff_added:
                text.append("+", Style(color=THEME["green"], bgcolor=g_bg))
            else:
                text.append(" ", Style(bgcolor=g_bg))

        # Content
        if is_table:
            if rel_idx == table_block.separator_index:
                render_table_separator(text, table_block.col_widths, bg=cursor_bg)
            else:
                is_header = table_block.separator_index >= 0 and rel_idx < table_block.separator_index
                cells = parse_table_cells(line)
                render_table_row(text, cells, table_block.col_widths, is_header, bg=cursor_bg)
        else:
            content_style = line_style(line, in_code, is_cursor, bg=cursor_bg)
            content = line if line else " "
            if self.wrap_width > 0 and len(content) > content_width:
                content = content[:content_width]

            if is_block_element(line, in_code):
                append_line_content(text, content, in_code, is_cursor, bg=cursor_bg)
            elif not in_code and not line.strip().startswith("```"):
                stripped = line.lstrip()
                heading_match = HEADING_RE.match(stripped)
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

            if self.search_query:
                apply_search_highlight(text, gutter_total, self.search_query)

        return self._make_strip(text, width)
