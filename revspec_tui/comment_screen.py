"""Thread popup with vim normal/insert modes — port of comment-input.ts."""
from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea
from rich.text import Text
from rich.style import Style

from .protocol import Thread, Message
from .theme import THEME

# Hint text per mode
NORMAL_HINTS = "[NORMAL]  [i/c] reply  [r] resolve  [q/Esc] close"
INSERT_HINTS = "[INSERT]  [Tab] send  [Esc] normal"


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
        width: 70;
        height: 80%;
        border: solid #89b4fa;
        background: #313244;
        padding: 1 2;
    }
    #comment-title {
        text-style: bold;
        color: #89b4fa;
        margin-bottom: 1;
    }
    #comment-history {
        height: 1fr;
        overflow-y: auto;
    }
    #comment-separator {
        height: 1;
    }
    #comment-input {
        height: 4;
        min-height: 4;
    }
    #comment-hints {
        color: #6c7086;
        height: 1;
    }
    """

    def __init__(
        self,
        line: int,
        existing_thread: Thread | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_resolve: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.line = line
        self.existing_thread = existing_thread
        self._on_submit = on_submit
        self._on_resolve = on_resolve
        self._mode: str = "normal" if existing_thread and existing_thread.messages else "insert"
        self._pending_g: bool = False

    def compose(self) -> ComposeResult:
        thread = self.existing_thread
        title = (
            f"Thread #{thread.id} (line {self.line})"
            if thread and thread.id
            else f"New comment on line {self.line}"
        )
        with Vertical(id="comment-dialog"):
            yield Static(title, id="comment-title")
            with VerticalScroll(id="comment-history"):
                if thread:
                    for msg in thread.messages:
                        yield self._render_message(msg)
            yield Static("", id="comment-separator")
            yield TextArea(id="comment-input")
            hints = NORMAL_HINTS if self._mode == "normal" else INSERT_HINTS
            yield Static(hints, id="comment-hints")

    def on_mount(self) -> None:
        if self._mode == "insert":
            self._enter_insert()
        else:
            self._enter_normal()
        # Scroll conversation to bottom
        history = self.query_one("#comment-history", VerticalScroll)
        history.scroll_end(animate=False)

    def _render_message(self, msg: Message) -> Static:
        is_reviewer = msg.author == "reviewer"
        prefix = "You" if is_reviewer else "AI"
        color = THEME["blue"] if is_reviewer else THEME["green"]
        text = Text()
        text.append(f"{prefix}: ", Style(color=color, bold=True))
        text.append(msg.text)
        return Static(text)

    def add_message(self, msg: Message) -> None:
        """Push a message into the conversation (for live watcher)."""
        history = self.query_one("#comment-history", VerticalScroll)
        history.mount(self._render_message(msg))
        history.scroll_end(animate=False)

    def _enter_insert(self) -> None:
        self._mode = "insert"
        textarea = self.query_one("#comment-input", TextArea)
        textarea.focus()
        self.query_one("#comment-hints", Static).update(INSERT_HINTS)
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.styles.border = ("solid", THEME["green"])

    def _enter_normal(self) -> None:
        self._mode = "normal"
        self.query_one("#comment-dialog", Vertical).focus()
        self.query_one("#comment-hints", Static).update(NORMAL_HINTS)
        dialog = self.query_one("#comment-dialog", Vertical)
        dialog.styles.border = ("solid", THEME["blue"])

    def on_key(self, event: Key) -> None:
        if self._mode == "insert":
            self._handle_insert_key(event)
        else:
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
            self.add_message(Message(author="reviewer", text=text))
            # Clear textarea and switch to normal
            textarea.clear()
            self._enter_normal()
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
            if self._on_resolve:
                self._on_resolve()
            self.dismiss(CommentResult("resolve"))
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
