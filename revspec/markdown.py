"""Markdown table parsing and rendering — port of ui/markdown.ts table functions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from rich.text import Text
from rich.style import Style

from .theme import THEME

SEPARATOR_RE = re.compile(r"^\|[\s:]*-+[\s:]*(\|[\s:]*-+[\s:]*)*\|?\s*$")

# Inline markdown regex — used for both stripping (display_width) and styled parsing.
# Groups: 1=bold-italic, 2=bold, 3=italic, 4=bold(underscore), 5=italic(underscore),
#         6=strikethrough, 7=link text, 8=code
_INLINE_MD_RE = re.compile(
    r"\*\*\*(.+?)\*\*\*"
    r"|\*\*(.+?)\*\*"
    r"|\*(.+?)\*"
    r"|(?<!\w)__(.+?)__(?!\w)"
    r"|(?<!\w)_(.+?)_(?!\w)"
    r"|~~(.+?)~~"
    r"|\[([^\]]+)\]\([^)]+\)"
    r"|`([^`]+)`"
)

# Style kwargs for each capture group (1-indexed)
_INLINE_STYLES: dict[int, dict] = {
    1: {"bold": True, "italic": True},           # ***bold italic***
    2: {"bold": True},                            # **bold**
    3: {"italic": True},                          # *italic*
    4: {"bold": True},                            # __bold__
    5: {"italic": True},                          # _italic_
    6: {"color": THEME["text_dim"], "strike": True},     # ~~strikethrough~~
    7: {"color": THEME["blue"], "underline": True},      # [link text](url)
    8: {"color": THEME["mauve"]},                         # `code`
}


def display_width(s: str) -> int:
    """Width of text after stripping inline markdown markers."""
    def _repl(m):
        for g in m.groups():
            if g is not None:
                return g
        return m.group(0)
    return len(_INLINE_MD_RE.sub(_repl, s))


def parse_inline_markdown(text: str) -> list[tuple[str, dict]]:
    """Parse inline markdown and return list of (text, style_kwargs) segments.

    Each segment is a tuple of (visible_text, style_kwargs_dict) where
    style_kwargs is a dict suitable for ``rich.style.Style(**kwargs)``.
    Plain text segments have an empty dict.
    """
    segments: list[tuple[str, dict]] = []
    last_end = 0
    for m in _INLINE_MD_RE.finditer(text):
        # Append any plain text before this match
        if m.start() > last_end:
            segments.append((text[last_end:m.start()], {}))
        # Find which group matched
        for group_idx in range(1, 9):
            content = m.group(group_idx)
            if content is not None:
                segments.append((content, dict(_INLINE_STYLES[group_idx])))
                break
        last_end = m.end()
    # Trailing plain text
    if last_end < len(text):
        segments.append((text[last_end:], {}))
    # If nothing matched, return the whole string as plain
    if not segments:
        segments.append((text, {}))
    return segments


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
    base_style = Style(color=THEME["text"], bold=is_header)
    dim = Style(color=THEME["text_dim"])
    for c, width in enumerate(col_widths):
        cell_text = cells[c] if c < len(cells) else ""
        dw = display_width(cell_text)
        padding = max(0, width - dw)
        border = "\u2502 " if c == 0 else " \u2502 "
        text.append(border, dim)
        # Parse inline markdown in cell content (bold, italic, code, links, etc.)
        for seg_text, seg_kwargs in parse_inline_markdown(cell_text):
            if seg_kwargs:
                seg_style = base_style + Style(**seg_kwargs)
                text.append(seg_text, seg_style)
            else:
                text.append(seg_text, base_style)
        if padding > 0:
            text.append(" " * padding)
    text.append(" \u2502", dim)


def _word_wrap_count(text: str, width: int) -> int:
    """Count extra visual lines from word-wrapping. Port of pager.ts wordWrap."""
    if width <= 0 or len(text) <= width:
        return 0
    count = 0
    remaining = text
    while len(remaining) > width:
        break_at = remaining.rfind(" ", 0, width)
        if break_at < 0:
            break_at = width
        remaining = remaining[break_at:].lstrip(" ")
        count += 1
    return count


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
            extra += _word_wrap_count(spec_lines[i], content_width)
        i += 1
    return extra
