"""Overlay modal screens — search, confirm, thread list, help, spinner, command."""

from __future__ import annotations

import time
from importlib.metadata import version as pkg_version

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static, Input
from rich.text import Text
from rich.style import Style

from .protocol import Thread
from .theme import THEME, status_icon, status_color
from .hints import build_hints


# ---------------------------------------------------------------------------
# Search modal
# ---------------------------------------------------------------------------

class SearchScreen(ModalScreen[tuple[str, int, int] | None]):
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

    def _count_matches(self, query: str) -> int:
        case_sensitive = query != query.lower()
        q = query if case_sensitive else query.lower()
        count = 0
        for line in self.spec_lines:
            hay = line if case_sensitive else line.lower()
            if q in hay:
                count += 1
        return count

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            self.dismiss(None)
            return
        match = self._find_match(query, self.start_line, 1)
        if match is not None:
            total = self._count_matches(query)
            self.dismiss((query, match, total))
        else:
            inp = self.query_one("#search-input", Input)
            inp.placeholder = f"No match for '{query}'"
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
            yield Static(build_hints([("y/Enter", "confirm"), ("q/Esc", "cancel")]), id="confirm-hints")

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
    }
    #thread-list-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    .thread-item {
        height: 1;
    }
    .thread-item-selected {
        height: 1;
        background: #45475a;
    }
    #thread-hints {
        height: 1;
    }
    """

    def __init__(self, threads: list[Thread], on_resolve=None, **kwargs):
        super().__init__(**kwargs)
        self._all_threads = [t for t in threads if t.status in ("open", "pending", "resolved")]
        self._filter_mode = "all"
        self.threads = self._filtered_sorted()
        self.selected_idx = 0
        self._on_resolve = on_resolve

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

    def _hints_text(self) -> Text:
        return build_hints([
            ("j/k", "navigate"),
            ("Enter", "jump"),
            ("r", "resolve"),
            ("Ctrl+f", f"filter: {self._filter_mode}"),
            ("q/Esc", "close"),
        ])

    def _render_item(self, t: Thread) -> Text:
        icon = status_icon(t.status)
        color = status_color(t.status)
        preview = self._preview_text(t)
        line_str = f"L{t.line}"
        text = Text()
        text.append(f" {icon} ", Style(color=color))
        text.append(f"{line_str:<5}", Style(color=THEME["text_dim"]))
        text.append(f" {preview}", Style(color=THEME["text"]))
        return text

    def compose(self) -> ComposeResult:
        with Vertical(id="thread-list-dialog"):
            yield Static(self._title_text(), id="thread-list-title")
            with VerticalScroll(id="thread-list-scroll"):
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
        elif event.key == "r":
            if self.threads and self._on_resolve:
                thread = self.threads[self.selected_idx]
                self._on_resolve(thread.id)
                # Refresh the item display + title after resolve toggle
                items = list(self.query(".thread-item, .thread-item-selected"))
                if self.selected_idx < len(items):
                    items[self.selected_idx].update(self._render_item(thread))
                self.query_one("#thread-list-title", Static).update(self._title_text())
        elif event.key == "ctrl+f":
            idx = (self.FILTER_CYCLE.index(self._filter_mode) + 1) % 3
            self._filter_mode = self.FILTER_CYCLE[idx]
            self.threads = self._filtered_sorted()
            self.selected_idx = 0
            await self._rebuild_items()

    async def _rebuild_items(self) -> None:
        """Remove old thread items and rebuild from current filter."""
        for widget in list(self.query(".thread-item, .thread-item-selected")):
            await widget.remove()
        scroll = self.query_one("#thread-list-scroll", VerticalScroll)
        if self.threads:
            for i, t in enumerate(self.threads):
                cls = "thread-item-selected" if i == 0 else "thread-item"
                widget = Static(self._render_item(t), classes=cls)
                scroll.mount(widget)
        else:
            scroll.mount(Static(" No threads match filter.", classes="thread-item"))
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
    #help-hints {
        height: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending_g = False

    def compose(self) -> ComposeResult:
        try:
            ver = pkg_version("revspec")
        except Exception:
            ver = "dev"
        blue = THEME["blue"]
        help_text = f"""\
[bold {blue}]revspec v{ver}[/]

[bold {blue}]Keyboard Reference[/]

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

[bold]Toggles[/]
  \\w           Toggle line wrapping
  \\n           Toggle line numbers

[bold]Other[/]
  Ctrl+R       Reload spec
  Ctrl+C       Force quit

[bold]Commands[/]
  :q/:wq       Quit (warns if unresolved)
  :q!          Force quit
  :{{N}}         Jump to line N
  :wrap        Toggle line wrapping
  :submit      Submit for rewrite (same as S)
  :approve     Approve spec (same as A)
  :resolve     Resolve thread (same as r)
  :reload      Reload spec (same as Ctrl+R)
  :help        Show this help (same as ?)
"""
        with Vertical(id="help-dialog"):
            with VerticalScroll(id="help-scroll"):
                yield Static(help_text)
            yield Static(build_hints([("j/k", "scroll"), ("q/Esc", "close")]), id="help-hints")

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
            yield Static(build_hints([("Ctrl+C", "cancel")]), id="spinner-hints")

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
# Command input (:command mode)
# ---------------------------------------------------------------------------

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
