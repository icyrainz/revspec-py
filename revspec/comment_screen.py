"""Thread popup with vim normal/insert modes — port of comment-input.ts."""
from __future__ import annotations

import time as _time
from collections.abc import Callable
from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea, Rule
from textual.widgets.text_area import TextAreaTheme
from rich.text import Text
from rich.style import Style

from .protocol import Thread, Message
from .theme import THEME, status_icon
from .hints import build_hints


def _render_hints(mode: str, resolved: bool = False) -> Text:
    """Render hint bar — mode label is now in the border title, not here."""
    if mode == "normal":
        resolve_label = "reopen" if resolved else "resolve"
        return build_hints(
            [("i/c", "reply"), ("r", resolve_label), ("q/Esc", "close")],
        )
    else:
        return build_hints(
            [("Tab", "send"), ("Esc", "normal")],
        )


# Custom TextArea theme to blend with dialog panel background
_COMMENT_THEME = TextAreaTheme(
    name="revspec-comment",
    base_style=Style(color=THEME["text"], bgcolor=THEME["panel"]),
    cursor_style=Style(color=THEME["crust"], bgcolor=THEME["text"]),
    cursor_line_style=Style(bgcolor=THEME["panel"]),
    gutter_style=Style(color=THEME["panel"], bgcolor=THEME["panel"]),
)


class CommentResult:
    """Result from CommentScreen — encodes what happened."""
    __slots__ = ("action",)

    def __init__(self, action: str):
        self.action = action  # "cancel" or "resolve"


class CommentScreen(ModalScreen[CommentResult]):
    """Modal thread popup with vim normal/insert modes.

    - New thread: starts in INSERT mode (green border, textarea focused)
    - Existing thread: starts in NORMAL mode (blue border, read conversation)
    - Tab submits text but does NOT dismiss — popup persists for conversation
    - r in normal mode triggers resolve
    - q/Esc in normal mode dismisses
    """

    CSS = """
    CommentScreen { align: center middle; }
    #comment-dialog {
        width: 70%;
        height: 80%;
        border: solid #89b4fa;
        background: #313244;
        padding: 1 2;
        border-title-align: left;
        border-title-color: #89b4fa;
    }
    #comment-history {
        height: 1fr;
        overflow-y: auto;
    }
    .msg-reviewer {
        border-left: solid #89b4fa;
        padding: 0 0 0 1;
        margin: 0 0 1 0;
    }
    .msg-ai {
        border-left: solid #a6e3a1;
        padding: 0 0 0 1;
        margin: 0 0 1 0;
    }
    #comment-separator {
        color: #45475a;
        margin: 0;
    }
    #comment-input {
        height: 4;
        min-height: 4;
        border: none;
    }
    #comment-context {
        height: 1;
        color: #6c7086;
        margin-bottom: 1;
    }
    #comment-hints {
        height: 1;
    }
    """

    def __init__(
        self,
        line: int,
        existing_thread: Thread | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_resolve: Callable[[], None] | None = None,
        spec_line_text: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.line = line
        self.existing_thread = existing_thread
        self._on_submit = on_submit
        self._on_resolve = on_resolve
        self._spec_line_text = spec_line_text
        self._mode: str = "normal" if existing_thread and existing_thread.messages else "insert"
        self._pending_g: bool = False

    def compose(self) -> ComposeResult:
        thread = self.existing_thread
        # Context line preview
        ctx = self._spec_line_text.strip()
        ctx_display = f" L{self.line}: {ctx[:70]}{'…' if len(ctx) > 70 else ''}" if ctx else f" L{self.line}"
        with Vertical(id="comment-dialog"):
            yield Static(ctx_display, id="comment-context")
            with VerticalScroll(id="comment-history"):
                if thread:
                    for msg in thread.messages:
                        yield self._render_message(msg)
            yield Rule(id="comment-separator")
            yield TextArea(id="comment-input", placeholder="Type your comment...")
            yield Static(_render_hints(self._mode), id="comment-hints")

    def _build_title(self) -> str:
        thread = self.existing_thread
        mode_label = self._mode.upper()
        if thread and thread.id:
            icon = status_icon(thread.status)
            return f" \\[{mode_label}] {icon} Thread #{thread.id} "
        else:
            return f" \\[{mode_label}] New comment on line {self.line} "

    def on_mount(self) -> None:
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.border_title = self._build_title()
        # Set initial mode
        if self._mode == "insert":
            self.query_one("#comment-input", TextArea).focus()
            self.query_one("#comment-hints", Static).update(_render_hints("insert"))
            dialog.styles.border = ("solid", THEME["mauve"])
            dialog.styles.border_title_color = THEME["mauve"]
        else:
            self._enter_normal()
        # Configure textarea theme
        textarea = self.query_one("#comment-input", TextArea)
        textarea.register_theme(_COMMENT_THEME)
        textarea.theme = "revspec-comment"
        textarea.show_line_numbers = False
        # Scroll conversation to bottom
        history = self.query_one("#comment-history", VerticalScroll)
        history.scroll_end(animate=False)

    def _render_message(self, msg: Message) -> Static:
        is_reviewer = msg.author == "reviewer"
        prefix = "You" if is_reviewer else "AI"
        ts_str = ""
        if msg.ts:
            ts_str = datetime.fromtimestamp(msg.ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        text = Text()
        text.append(prefix, Style(color=THEME["text_muted"]))
        if ts_str:
            text.append(f"  {ts_str}", Style(color=THEME["text_muted"]))
        text.append("\n")
        text.append(msg.text, Style(color=THEME["text"]))
        css_class = "msg-reviewer" if is_reviewer else "msg-ai"
        return Static(text, classes=css_class)

    def update_title(self, thread_id: str = "", line: int = 0) -> None:
        """Update dialog title (e.g. after new thread creation)."""
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.border_title = self._build_title()

    def update_status(self, status: str) -> None:
        """Update status indicator, border color, and hints after resolve/unresolve."""
        thread = self.existing_thread
        if not thread:
            return
        resolved = status == "resolved"
        border_color = THEME["green"] if resolved else THEME["blue"]
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.border_title = self._build_title()
        if self._mode == "normal":
            dialog.styles.border = ("solid", border_color)
            dialog.styles.border_title_color = border_color
            self.query_one("#comment-hints", Static).update(_render_hints("normal", resolved=resolved))

    def add_message(self, msg: Message) -> None:
        """Push a message into the conversation (for live watcher)."""
        history = self.query_one("#comment-history", VerticalScroll)
        history.mount(self._render_message(msg))
        history.scroll_end(animate=False)

    def _enter_insert(self) -> None:
        self._mode = "insert"
        textarea = self.query_one("#comment-input", TextArea)
        textarea.focus()
        self.query_one("#comment-hints", Static).update(_render_hints("insert"))
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.styles.border = ("solid", THEME["mauve"])
        dialog.styles.border_title_color = THEME["mauve"]
        dialog.border_title = self._build_title()

    def _enter_normal(self) -> None:
        self._mode = "normal"
        self.query_one("#comment-history", VerticalScroll).focus()
        resolved = self.existing_thread and self.existing_thread.status == "resolved"
        self.query_one("#comment-hints", Static).update(_render_hints("normal", resolved=bool(resolved)))
        border_color = THEME["green"] if resolved else THEME["blue"]
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.styles.border = ("solid", border_color)
        dialog.styles.border_title_color = border_color
        dialog.border_title = self._build_title()

    def on_key(self, event: Key) -> None:
        # Ctrl+C force dismisses from any mode
        if event.key == "ctrl+c":
            event.prevent_default()
            event.stop()
            self.dismiss(CommentResult("cancel"))
            return
        if self._mode == "insert":
            # Only intercept escape/tab; let all other keys reach TextArea
            if event.key in ("escape", "tab"):
                self._handle_insert_key(event)
        else:
            event.stop()  # prevent bubbling in normal mode
            self._handle_normal_key(event)

    def _handle_insert_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self._enter_normal()
        elif event.key == "tab":
            event.prevent_default()
            event.stop()
            textarea = self.query_one("#comment-input", TextArea)
            text = textarea.text.strip()
            if not text:
                return
            # Submit callback — app handles state + JSONL
            if self._on_submit:
                self._on_submit(text)
            # Append to conversation display
            self.add_message(Message(author="reviewer", text=text, ts=int(_time.time() * 1000)))
            # Clear textarea — stay in insert mode for chat-like flow
            textarea.clear()
        # All other keys pass through to textarea

    def _handle_normal_key(self, event: Key) -> None:
        event.prevent_default()
        event.stop()
        key = event.key

        if key in ("escape", "q"):
            self.dismiss(CommentResult("cancel"))
        elif key in ("i", "c"):
            self._enter_insert()
        elif key == "r":
            if not self.existing_thread:
                return
            if self._on_resolve:
                was_resolved = self.existing_thread and self.existing_thread.status == "resolved"
                self._on_resolve()
                if not was_resolved:
                    # Resolving → close popup (thread is done)
                    self.dismiss(CommentResult("resolve"))
                # Reopening → stay open (continue conversation)
        elif key in ("j", "down"):
            self.query_one("#comment-history", VerticalScroll).scroll_down()
        elif key in ("k", "up"):
            self.query_one("#comment-history", VerticalScroll).scroll_up()
        elif key == "ctrl+d":
            h = self.query_one("#comment-history", VerticalScroll)
            h.scroll_to(y=h.scroll_offset.y + 5)
        elif key == "ctrl+u":
            h = self.query_one("#comment-history", VerticalScroll)
            h.scroll_to(y=max(0, h.scroll_offset.y - 5))
        elif key == "g":
            if self._pending_g:
                self._pending_g = False
                self.query_one("#comment-history", VerticalScroll).scroll_home()
            else:
                self._pending_g = True
                self.set_timer(0.3, self._clear_pending_g)
        elif key in ("shift+g", "G"):
            self._pending_g = False
            self.query_one("#comment-history", VerticalScroll).scroll_end()

    def _clear_pending_g(self) -> None:
        self._pending_g = False
