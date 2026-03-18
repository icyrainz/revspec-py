"""Pure rendering functions for spec line styling — no Textual dependency.

All functions operate on Rich Text objects and return/mutate them.
"""

from __future__ import annotations

import re

from rich.text import Text
from rich.style import Style

from .theme import THEME
from .markdown import parse_inline_markdown


# Regex for horizontal rules: 3+ of the same char (-, *, _) with optional spaces
_HR_RE = re.compile(r"^(\s*[-*_]\s*){3,}$")
# Regex for unordered list items: optional indent + marker + space + content
_UL_RE = re.compile(r"^(\s*)([-*+])\s+(.*)")


def line_style(line: str, in_code_block: bool, is_cursor: bool) -> Style:
    """Determine the Rich Style for a spec line based on content and context."""
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
    else:
        return Style(color=THEME["text"], bgcolor=bg)


def is_block_element(line: str, in_code_block: bool) -> bool:
    """Return True if line needs multi-segment rendering (blockquote, list, hr)."""
    if in_code_block or line.strip().startswith("```"):
        return False
    stripped = line.lstrip()
    if stripped.startswith("> "):
        return True
    if _UL_RE.match(line):
        return True
    if _HR_RE.match(line):
        return True
    return False


def append_line_content(
    text: Text, line: str, in_code_block: bool, is_cursor: bool,
) -> None:
    """Append styled markdown content segments to *text*.

    Handles blockquotes (│ prefix), list items (• bullet), and horizontal
    rules (─×40).  Falls back to ``line_style`` for everything else.
    """
    bg = THEME["panel"] if is_cursor else None

    if not in_code_block and not line.strip().startswith("```"):
        stripped = line.lstrip()

        # Horizontal rule: --- / *** / ___
        if _HR_RE.match(line):
            text.append("\u2500" * 40, Style(color=THEME["text_dim"], dim=True, bgcolor=bg))
            return

        # Blockquote: > text  →  │ <text in italic + text_muted>
        if stripped.startswith("> "):
            text.append("\u2502 ", Style(color=THEME["mauve"], bgcolor=bg))
            bq_style = Style(color=THEME["text_muted"], italic=True, bgcolor=bg)
            append_inline_styled(text, stripped[2:], bq_style)
            return

        # Unordered list: - / * / + item  →  • item
        ul_match = _UL_RE.match(line)
        if ul_match:
            indent = ul_match.group(1)
            item_text = ul_match.group(3)
            text.append(indent + "\u2022 ", Style(color=THEME["yellow"], bgcolor=bg))
            item_style = Style(color=THEME["text"], bgcolor=bg)
            append_inline_styled(text, item_text, item_style)
            return

    # Default: single-style rendering
    style = line_style(line, in_code_block, is_cursor)
    text.append(line if line else " ", style)


def append_inline_styled(
    text: Text, content: str, base_style: Style,
) -> None:
    """Append *content* to *text*, rendering inline markdown with styles."""
    for seg_text, seg_kwargs in parse_inline_markdown(content):
        if seg_kwargs:
            seg_style = base_style + Style(**seg_kwargs)
            text.append(seg_text, seg_style)
        else:
            text.append(seg_text, base_style)


def append_highlighted(
    text: Text, content: str, query: str,
    base_style: Style,
) -> None:
    """Highlight search query matches within content."""
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
            Style(color=THEME["crust"], bgcolor=THEME["yellow"], bold=True),
        )
        pos = idx + len(query)


def gutter_width(spec_line_count: int, show_line_numbers: bool) -> tuple[int, int]:
    """Return (num_width, gutter_total) based on show_line_numbers."""
    num_width = max(len(str(spec_line_count)), 3) if show_line_numbers else 0
    gutter_total = (2 + num_width + 2) if show_line_numbers else 3
    return num_width, gutter_total
