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


HEADING_RE = re.compile(r"^(#{1,6})\s+")


def line_style(line: str, in_code_block: bool, is_cursor: bool, bg: str | None = None) -> Style:
    """Determine the Rich Style for a spec line based on content and context.

    If *bg* is provided, it overrides the default background color.
    """
    if bg is None:
        bg = THEME["panel"] if is_cursor else THEME["crust"]

    # Fence line (``` markers) — dim, code block background
    if line.strip().startswith("```"):
        code_bg = THEME["panel"] if is_cursor else THEME["mantle"]
        return Style(color=THEME["text_dim"], bgcolor=code_bg)
    # Inside code block — green, code block background
    if in_code_block:
        code_bg = THEME["panel"] if is_cursor else THEME["mantle"]
        return Style(color=THEME["green"], bgcolor=code_bg)

    stripped = line.lstrip()
    heading_match = HEADING_RE.match(stripped)
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
    bg: str | None = None,
) -> None:
    """Append styled markdown content segments to *text*.

    Handles blockquotes (│ prefix), list items (• bullet), and horizontal
    rules (─×40).  Falls back to ``line_style`` for everything else.
    If *bg* is provided, it overrides the default background color.
    """
    if bg is None:
        bg = THEME["panel"] if is_cursor else THEME["crust"]

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


def smartcase_prepare(query: str) -> tuple[str, bool]:
    """Return (normalized_query, case_sensitive) using smartcase rules.

    If *query* contains any uppercase character, match case-sensitively.
    Otherwise match case-insensitively (lowered).
    """
    case_sensitive = query != query.lower()
    return (query if case_sensitive else query.lower(), case_sensitive)


HIGHLIGHT_STYLE = Style(color=THEME["crust"], bgcolor=THEME["yellow"], bold=True)


def apply_search_highlight(text: Text, gutter_len: int, query: str) -> None:
    """Overlay search highlights onto an already-styled Rich Text.

    Searches the rendered plain text (after the gutter) for *query* matches
    (smartcase) and applies highlight styling at those positions.
    """
    if not query:
        return
    q, case_sensitive = smartcase_prepare(query)
    plain = text.plain
    haystack = plain[gutter_len:] if case_sensitive else plain[gutter_len:].lower()
    pos = 0
    while pos < len(haystack):
        idx = haystack.find(q, pos)
        if idx == -1:
            break
        start = gutter_len + idx
        end = start + len(query)
        text.stylize(HIGHLIGHT_STYLE, start, end)
        pos = idx + len(query)


def gutter_width(spec_line_count: int, show_line_numbers: bool) -> tuple[int, int]:
    """Return (num_width, gutter_total) based on show_line_numbers."""
    num_width = max(len(str(spec_line_count)), 3) if show_line_numbers else 0
    gutter_total = (2 + num_width + 2) if show_line_numbers else 3
    return num_width, gutter_total
