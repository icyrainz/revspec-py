"""Pure status bar and hint bar builders — no Textual dependency."""

from __future__ import annotations

from rich.text import Text
from rich.style import Style

from .theme import THEME
from .navigation import heading_breadcrumb
from .protocol import Thread


def build_hints(
    hints: list[tuple[str, str]],
    prefix: str | None = None,
    prefix_style: Style | None = None,
) -> Text:
    """Build a styled hint bar from (key, action) pairs.

    Matches the TypeScript buildHints() format:
    - ``[key]`` in THEME["blue"]
    - ``action`` in THEME["text_muted"]
    - Double space between hint pairs

    Optional prefix (e.g. "[NORMAL]", "[INSERT]") rendered before the hints.
    """
    text = Text()
    text.append(" ")
    if prefix:
        text.append(prefix, prefix_style or Style(color=THEME["blue"], bold=True))
        text.append("  ")
    key_style = Style(color=THEME["blue"])
    action_style = Style(color=THEME["text_muted"])
    for i, (key, action) in enumerate(hints):
        text.append(f"[{key}]", key_style)
        text.append(f" {action}", action_style)
        if i < len(hints) - 1:
            text.append("  ")
    return text


def build_top_bar(
    *,
    file_name: str,
    threads: list[Thread],
    unread_count: int,
    cursor_line: int,
    line_count: int,
    spec_lines: list[str],
    mtime_changed: bool,
) -> Text:
    """Build the top status bar text."""
    text = Text()
    text.append(f" {file_name}", Style(color=THEME["text"], bold=True))

    # Thread progress
    if threads:
        resolved = sum(1 for t in threads if t.status == "resolved")
        total = len(threads)
        color = THEME["green"] if resolved == total else THEME["yellow"]
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(f"{resolved}/{total} resolved", Style(color=color))

    # Unread replies
    if unread_count > 0:
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(
            f"{unread_count} new {'reply' if unread_count == 1 else 'replies'}",
            Style(color=THEME["yellow"], bold=True),
        )

    # Spec mutation guard
    if mtime_changed:
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(
            "!! Spec changed externally (Ctrl+R to reload)",
            Style(color=THEME["red"], bold=True),
        )

    # Position
    cur = cursor_line
    total = line_count
    if cur <= 1:
        pos_label = "Top"
    elif cur >= total:
        pos_label = "Bot"
    else:
        pos_label = f"{round((cur - 1) / max(1, total - 1) * 100)}%"
    text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
    text.append(f"L{cur}/{total} {pos_label}", Style(color=THEME["text_muted"]))

    # Section breadcrumb
    crumb = heading_breadcrumb(spec_lines, cur)
    if crumb:
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(crumb, Style(color=THEME["text_dim"], italic=True))

    return text


def build_bottom_bar(
    *,
    message: str | None = None,
    icon: str | None = None,
    thread: Thread | None = None,
    has_active_message: bool = False,
) -> Text:
    """Build the bottom status bar text."""
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
        if thread and thread.messages and not has_active_message:
            first = thread.messages[0].text.replace("\n", " ")
            preview = first[:59] + "\u2026" if len(first) > 60 else first
            replies = len(thread.messages) - 1
            reply_str = (
                f" ({replies} {'reply' if replies == 1 else 'replies'})"
                if replies > 0
                else ""
            )
            text.append(
                f" {preview}{reply_str} [{thread.status}]",
                Style(color=THEME["text_muted"]),
            )
        else:
            has_thread = thread is not None
            hint_pairs: list[tuple[str, str]] = [
                ("j/k", "navigate"),
                ("c", "comment"),
            ]
            if has_thread:
                hint_pairs.append(("r", "resolve"))
            hint_pairs.extend([
                ("S", "submit"),
                ("A", "approve"),
                ("?", "help"),
            ])
            text = build_hints(hint_pairs)
    return text
