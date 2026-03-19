"""Catppuccin Mocha theme — single source of truth for colors.

All Style() calls and inline markdown styles MUST reference THEME keys.
CSS strings in Textual widgets cannot use Python variables — they repeat
the hex values from THEME. When changing a color, grep for the hex value
across all .py files to update CSS strings in sync.
"""

THEME = {
    "base": None,  # None = transparent (inherit terminal background)
    "crust": "#1e1e2e",  # darkest bg — used for search highlight contrast
    "mantle": "#181825",  # code block bg — slightly darker than crust
    "panel": "#313244",
    "text": "#cdd6f4",
    "text_muted": "#a6adc8",
    "text_dim": "#6c7086",
    "blue": "#89b4fa",
    "green": "#a6e3a1",
    "red": "#f38ba8",
    "yellow": "#f9e2af",
    "mauve": "#cba6f7",
    "border": "#45475a",
    "border_accent": "#89b4fa",
    "success": "#a6e3a1",
    "warning": "#f9e2af",
    "error": "#f38ba8",
    "info": "#89b4fa",
}

STATUS_ICONS = {
    "open": "\u258f",      # ▏ thin bar
    "pending": "\u258c",   # ▌ left half block
    "resolved": "\u2588",  # █ full block
    "outdated": "\u258f",  # ▏ thin bar
}

STATUS_COLORS = {
    "open": THEME["text"],
    "pending": THEME["text"],
    "resolved": THEME["green"],
}

def status_icon(status: str) -> str:
    """Get the gutter icon for a thread status."""
    return STATUS_ICONS.get(status, "\u258f")

def status_color(status: str, is_unread: bool = False) -> str:
    """Get the color for a thread status. Unread overrides to yellow."""
    if is_unread:
        return THEME["yellow"]
    return STATUS_COLORS.get(status, THEME["text"])
