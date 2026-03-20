"""Textual-based TUI for revspec — prototype."""

from __future__ import annotations

import os
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.widgets import Static
from rich.text import Text
from rich.style import Style

from .state import ReviewState
from .protocol import LiveEvent, Message, append_event, read_events, replay_events_to_threads, slice_to_current_session
from .theme import THEME
from .commands import parse_command
from .hints import build_hints, build_top_bar, build_bottom_bar
from .key_dispatch import SequenceRouter
from .navigation import JumpList, HeadingIndex
from .pager import SpecPager
from .diff_state import DiffState
from .renderer import smartcase_prepare
from .overlays import (
    SearchScreen, ConfirmScreen, ThreadListScreen,
    HelpScreen, SpinnerScreen, CommandScreen,
)
from .watcher_service import LiveWatcherService, is_watcher_running
from .comment_screen import CommentScreen, CommentResult


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class RevspecApp(App):
    """Textual-based revspec TUI."""

    CSS = """
    #top-bar {
        height: 1;
        background: #313244;
        color: #cdd6f4;
    }
    #pager-scroll {
        height: 1fr;
        background: #1e1e2e;
    }
    #bottom-bar {
        height: 1;
        background: #313244;
        color: #a6adc8;
    }
    """

    BINDINGS = [
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(self, spec_file: str, **kwargs):
        super().__init__(**kwargs)
        self.spec_file = spec_file
        self.spec_content = Path(spec_file).read_text(encoding="utf-8")
        spec_lines = self.spec_content.split("\n")

        self.state = ReviewState(spec_lines)
        self.pager_widget: SpecPager | None = None
        self.search_query: str | None = None

        # JSONL path
        base = Path(spec_file)
        self.jsonl_path = str(base.parent / (base.stem + ".review.jsonl"))

        # Replay existing events — only from the current session
        if os.path.exists(self.jsonl_path):
            events, _ = read_events(self.jsonl_path)
            for t in replay_events_to_threads(slice_to_current_session(events)):
                existing = self.state._find_thread(t.id)
                if not existing:
                    self.state.threads.append(t)
                    self.state._thread_by_id[t.id] = t
                    self.state._thread_by_line[t.line] = t
                else:
                    existing.messages = t.messages
                    existing.status = t.status
            # Mark new session boundary (dedup: skip if last event is already session-start)
            if events and events[-1].type != "session-start":
                append_event(self.jsonl_path, LiveEvent(
                    type="session-start", author="reviewer",
                    ts=int(time.time() * 1000),
                ))

        # Multi-key sequence state
        self._pending_key: str | None = None
        self._pending_timer: float = 0
        self._pending_key_timer: object | None = None
        self._seq_router = SequenceRouter()
        self._count_prefix: int = 0  # numeric prefix for motions (5j, 3G)

        # Jump list — mirrors vim :jumps (TS app.ts:161-184)
        self._jump_list = JumpList()

        # Precomputed heading index
        self._heading_index = HeadingIndex(spec_lines)

        # Transient message timer handle
        self._message_timer = None

        # Line wrapping
        self._wrap_enabled = True

        # Scroll margin — lines of context kept above/below cursor on search jumps
        self.search_scroll_margin: int = 5

        # Spec mutation guard
        self._spec_mtime = Path(spec_file).stat().st_mtime
        self._spec_mtime_changed = False
        self._diff_state: DiffState | None = None

        # Submit flow
        self._spec_poll_timer = None

        # Live watcher
        self._live_watcher_timer = None
        self._watcher_service = LiveWatcherService(self.jsonl_path)

    def compose(self) -> ComposeResult:
        yield Static(self._top_bar_text(), id="top-bar")
        self.pager_widget = SpecPager(self.state, id="pager-scroll")
        yield self.pager_widget
        yield Static(self._bottom_bar_text(), id="bottom-bar")

    def on_mount(self) -> None:
        if self.pager_widget:
            self.pager_widget.wrap_width = self.size.width if self.size.width > 0 else 200
            self.pager_widget.invalidate_table_cache()
        self._refresh()
        # Start live watcher polling
        self._watcher_service.init_offset()
        self._live_watcher_timer = self.set_interval(0.5, self._check_live_events)
        # Welcome hint on first launch
        if not self.state.threads:
            self._show_transient("Navigate to a line and press c to comment  |  ? for help", "info", 8.0)

    def _do_reload(self, new_content: str, new_mtime: float) -> None:
        """Shared reload logic — reset state, re-replay JSONL, reset UI."""
        old_lines = list(self.state.spec_lines)
        new_lines = new_content.split("\n")
        self.state.reset(new_lines)
        # Re-replay JSONL to restore thread state (current session only)
        if os.path.exists(self.jsonl_path):
            events, _ = read_events(self.jsonl_path)
            for t in replay_events_to_threads(slice_to_current_session(events)):
                self.state.threads.append(t)
                self.state._thread_by_id[t.id] = t
                self.state._thread_by_line[t.line] = t
        self._spec_mtime = new_mtime
        self._spec_mtime_changed = False
        self.search_query = None
        self._jump_list = JumpList()
        self._heading_index.rebuild(new_lines)
        if self.pager_widget:
            self.pager_widget.invalidate_table_cache()
        self._watcher_service.init_offset()
        # Compute diff between old and new spec
        diff = DiffState(old_lines, new_lines)
        if diff.has_diff():
            self._diff_state = diff
        else:
            self._diff_state = None
        if self.pager_widget:
            self.pager_widget.diff_state = self._diff_state

    def _check_spec_reload(self) -> None:
        """Poll spec file mtime for reload after submit."""
        try:
            current_mtime = Path(self.spec_file).stat().st_mtime
            if current_mtime != self._spec_mtime:
                if self._spec_poll_timer:
                    self._spec_poll_timer.stop()
                    self._spec_poll_timer = None
                # Dismiss spinner if open
                if isinstance(self.screen, SpinnerScreen):
                    self.screen.dismiss("success")
                new_content = Path(self.spec_file).read_text(encoding="utf-8")
                self._do_reload(new_content, current_mtime)
                # _refresh() and transient deferred to on_spinner_done("success")
        except OSError:
            pass

    def _reload_spec(self) -> None:
        """Manual spec reload (Ctrl+R)."""
        try:
            current_mtime = Path(self.spec_file).stat().st_mtime
            if current_mtime == self._spec_mtime:
                self._show_transient("Spec is up to date", "info", 1.5)
                return
            new_content = Path(self.spec_file).read_text(encoding="utf-8")
            self._do_reload(new_content, current_mtime)
            self._refresh()
            self._show_transient("Spec reloaded", "success", 1.5)
        except OSError:
            self._show_transient("Failed to reload spec", "warn", 2.0)

    def _check_live_events(self) -> None:
        """Poll JSONL for owner events (AI replies) and check spec mtime."""
        # Spec mutation guard — check mtime on timer, not per-keypress
        spec_missing = False
        try:
            current_mtime = Path(self.spec_file).stat().st_mtime
            changed = current_mtime != self._spec_mtime
        except OSError:
            changed = True
            spec_missing = True
        if changed and not self._spec_mtime_changed:
            self._spec_mtime_changed = True
            self.query_one("#top-bar", Static).update(self._top_bar_text())
            if spec_missing:
                self._show_transient("Spec file is missing or inaccessible", "warn", 3.0)

        result = self._watcher_service.poll()
        if not result.has_new:
            return

        last_reply_line = None
        last_reply_thread_id = None
        changed = False
        for e in result.events:
            if e.type == "reply" and e.thread_id and e.text:
                self.state.add_owner_reply(e.thread_id, e.text, e.ts)
                t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                if t:
                    last_reply_line = t.line
                    last_reply_thread_id = e.thread_id
                # Push into open CommentScreen if it's showing this thread
                active = self.screen
                if isinstance(active, CommentScreen) and active.existing_thread and active.existing_thread.id == e.thread_id:
                    active.add_message(Message(author="owner", text=e.text, ts=e.ts))
                changed = True
            elif e.type == "resolve" and e.thread_id:
                t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                if t and t.status != "resolved":
                    t.status = "resolved"
                    changed = True
            elif e.type == "unresolve" and e.thread_id:
                t = next((t for t in self.state.threads if t.id == e.thread_id), None)
                if t and t.status == "resolved":
                    t.status = "open"
                    changed = True
            elif e.type == "delete" and e.thread_id:
                before = len(self.state.threads)
                self.state.delete_thread(e.thread_id)
                if len(self.state.threads) < before:
                    changed = True
        if changed:
            self._refresh()
            # Only flash if CommentScreen is not open for this thread
            if last_reply_line:
                active = self.screen
                suppress = isinstance(active, CommentScreen) and active.existing_thread and active.existing_thread.id == last_reply_thread_id
                if not suppress:
                    self._show_transient(f"AI replied on line {last_reply_line}", "info")

    def _top_bar_text(self) -> Text:
        return build_top_bar(
            file_name=Path(self.spec_file).name,
            threads=self.state.threads,
            unread_count=self.state.unread_count,
            cursor_line=self.state.cursor_line,
            line_count=self.state.line_count,
            breadcrumb=self._heading_index.breadcrumb(self.state.cursor_line),
            mtime_changed=self._spec_mtime_changed,
            diff_stats=self._diff_state.stats if self._diff_state and self._diff_state.is_active else None,
        )

    @staticmethod
    def _build_hints(hints: list[tuple[str, str]]) -> Text:
        return build_hints(hints)

    def _bottom_bar_text(self, message: str | None = None, icon: str | None = None) -> Text:
        return build_bottom_bar(
            message=message,
            icon=icon,
            thread=self.state.thread_at_line(self.state.cursor_line),
            has_active_message=self._message_timer is not None,
        )

    def _write_event(self, event: LiveEvent) -> bool:
        """Write a JSONL event, showing a warning on failure. Returns True on success."""
        try:
            append_event(self.jsonl_path, event)
            return True
        except OSError:
            self._show_transient("Failed to save — check disk space/permissions", "warn", 3.0)
            return False

    def _refresh(self) -> None:
        if self.pager_widget:
            self.pager_widget.cursor_line = self.state.cursor_line
            if self.search_query:
                self.pager_widget.search_query = self.search_query
            else:
                self.pager_widget.search_query = ""
            self.pager_widget.refresh_content()
            self.pager_widget.scroll_cursor_visible()
        self.query_one("#top-bar", Static).update(self._top_bar_text())
        if self._message_timer is None:
            self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())

    def _scroll_to_cursor(self, center: bool = False, margin: int = 0) -> None:
        """Scroll the pager to keep the cursor line visible."""
        if self.pager_widget:
            self.pager_widget.scroll_cursor_visible(center=center, margin=margin)

    def _show_transient(self, message: str, icon: str | None = None, duration: float = 1.5) -> None:
        if self._message_timer is not None:
            self._message_timer.stop()
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text(message, icon))
        self._message_timer = self.set_timer(duration, self._clear_transient)

    def _clear_transient(self) -> None:
        self._message_timer = None
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())

    # --- Jump list ---

    def _push_jump(self) -> None:
        self._jump_list.push(self.state.cursor_line)

    def _jump_backward(self) -> None:
        target = self._jump_list.backward(self.state.cursor_line, self.state.line_count)
        if target is not None:
            self.state.cursor_line = target
            self._refresh()

    def _jump_forward(self) -> None:
        target = self._jump_list.forward(self.state.line_count)
        if target is not None:
            self.state.cursor_line = target
            self._refresh()

    def _jump_swap(self) -> None:
        target = self._jump_list.swap(self.state.cursor_line, self.state.line_count)
        if target is not None:
            self.state.cursor_line = target
            self._refresh()

    # --- Multi-key sequence handling ---

    def _check_pending(self) -> str | None:
        """Return and clear pending key if still valid."""
        if self._pending_key and (time.monotonic() - self._pending_timer) < 0.3:
            k = self._pending_key
            self._pending_key = None
            self._cancel_pending_hint_timer()
            self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())
            return k
        self._pending_key = None
        self._cancel_pending_hint_timer()
        return None

    def _cancel_pending_hint_timer(self) -> None:
        """Cancel the pending key hint timer if active."""
        if self._pending_key_timer is not None:
            self._pending_key_timer.stop()
            self._pending_key_timer = None

    def _clear_pending_hint(self) -> None:
        """Restore the bottom bar after the pending key times out."""
        self._pending_key_timer = None
        self.query_one("#bottom-bar", Static).update(self._bottom_bar_text())

    # --- Key dispatch ---

    def on_key(self, event: Key) -> None:
        # Skip key handling when a modal overlay is active
        if self.screen is not self.screen_stack[0]:
            return

        key = event.key

        # Accumulate digit prefix (e.g. 5j = move 5 lines)
        if key.isdigit() and not self._pending_key:
            digit = int(key)
            # Don't treat 0 as count start (0 could be a motion later)
            if self._count_prefix > 0 or digit > 0:
                event.prevent_default()
                self._count_prefix = self._count_prefix * 10 + digit
                return

        # Check for second key of a sequence
        pending = self._check_pending()

        if pending:
            event.prevent_default()
            handler_name = self._seq_router.resolve(pending, key)
            if handler_name:
                getattr(self, handler_name)()
            else:
                self._handle_single_key(event, key)
            self._count_prefix = 0
            return

        # Single keys that start sequences
        if self._seq_router.is_prefix(key):
            event.prevent_default()
            self._start_pending(key)
            return

        # Single-key actions
        event.prevent_default()
        self._handle_single_key(event, key)
        self._count_prefix = 0

    def _start_pending(self, key: str) -> None:
        """Start a pending multi-key sequence."""
        self._count_prefix = 0
        self._cancel_pending_hint_timer()
        self._pending_key = key
        self._pending_timer = time.monotonic()
        # Show pending key hint in bottom bar with available options
        hints = self._seq_router.hints_for_prefix(key)
        if hints:
            self.query_one("#bottom-bar", Static).update(self._build_hints(hints))
        else:
            self.query_one("#bottom-bar", Static).update(Text(f" {key}...", Style(color=THEME["text_dim"])))
        self._pending_key_timer = self.set_timer(0.35, self._clear_pending_hint)

    def _handle_single_key(self, event: Key, key: str) -> None:
        """Process a single key press (non-sequence)."""
        # Check if this key starts a new sequence
        if self._seq_router.is_prefix(key):
            self._start_pending(key)
            return

        count = max(1, self._count_prefix)
        match key:
            case "j" | "down":
                new_line = min(self.state.cursor_line + count, self.state.line_count)
                if new_line != self.state.cursor_line:
                    self.state.cursor_line = new_line
                    self._refresh()
            case "k" | "up":
                new_line = max(self.state.cursor_line - count, 1)
                if new_line != self.state.cursor_line:
                    self.state.cursor_line = new_line
                    self._refresh()
            case "ctrl+d":
                view_h = self.pager_widget.size.height if self.pager_widget else self.size.height - 2
                half = max(1, view_h // 2) * count
                self.state.cursor_line = min(self.state.cursor_line + half, self.state.line_count)
                self._refresh()
            case "ctrl+u":
                view_h = self.pager_widget.size.height if self.pager_widget else self.size.height - 2
                half = max(1, view_h // 2) * count
                self.state.cursor_line = max(self.state.cursor_line - half, 1)
                self._refresh()
            case "shift+g" | "G":
                self._push_jump()
                if self._count_prefix > 0:
                    self.state.cursor_line = min(self._count_prefix, self.state.line_count)
                else:
                    self.state.cursor_line = self.state.line_count
                self._refresh()
            case "ctrl+o":
                self._jump_backward()
            case "ctrl+i" | "tab":
                self._jump_forward()
            case "shift+h" | "H":
                self._push_jump()
                if self.pager_widget:
                    scroll_top = round(self.pager_widget.scroll_offset.y)
                    self.state.cursor_line = max(1, self.pager_widget.spec_line_at_visual_row(scroll_top))
                self._refresh()
            case "shift+m" | "M":
                self._push_jump()
                if self.pager_widget:
                    scroll_top = round(self.pager_widget.scroll_offset.y)
                    view_h = self.pager_widget.size.height
                    mid_row = scroll_top + view_h // 2
                    self.state.cursor_line = max(1, min(self.pager_widget.spec_line_at_visual_row(mid_row), self.state.line_count))
                self._refresh()
            case "shift+l" | "L":
                self._push_jump()
                if self.pager_widget:
                    scroll_top = round(self.pager_widget.scroll_offset.y)
                    view_h = self.pager_widget.size.height
                    bottom_row = scroll_top + view_h - 1
                    self.state.cursor_line = max(1, min(self.pager_widget.spec_line_at_visual_row(bottom_row), self.state.line_count))
                self._refresh()
            case "shift+r" | "R":
                pending_threads = [t for t in self.state.threads if t.status == "pending"]
                if not pending_threads:
                    self._show_transient("No pending threads")
                else:
                    self.state.resolve_all_pending()
                    for t in pending_threads:
                        self._write_event(LiveEvent(
                            type="resolve", thread_id=t.id,
                            author="reviewer", ts=int(time.time() * 1000),
                        ))
                    self._refresh()
                    self._show_transient(f"Resolved {len(pending_threads)} pending thread(s)", "success")
            case "c":
                self._open_comment()
            case "t":
                self._open_thread_list()
            case "r":
                self._resolve_current()
            case "slash":
                self._open_search()
            case "n":
                self._search_next(1)
            case "shift+n" | "N":
                self._search_next(-1)
            case "shift+s" | "S":
                self._submit()
            case "shift+a" | "A":
                self._approve()
            case "question_mark":
                self.push_screen(HelpScreen())
            case "colon":
                self._open_command_mode()
            case "ctrl+r":
                self._reload_spec()
            case "escape":
                if self.search_query:
                    self.search_query = None
                    self._refresh()
            case "ctrl+c":
                self._exit_tui("session-end")
            case _:
                pass  # ignore unmapped keys

    # --- Sequence handler methods (referenced by _SEQUENCE_REGISTRY) ---

    def _seq_go_top(self) -> None:
        self._push_jump()
        self.state.cursor_line = 1
        self._refresh()

    def _seq_center(self) -> None:
        self._scroll_to_cursor(center=True)

    def _seq_next_thread(self) -> None:
        line = self.state.next_thread()
        if line:
            wrapped = line < self.state.cursor_line
            self._push_jump()
            self.state.cursor_line = line
            self._refresh()
            if wrapped:
                self._show_transient("Wrapped to first thread", "info", 1.2)
        else:
            self._show_transient("No threads")

    def _seq_prev_thread(self) -> None:
        line = self.state.prev_thread()
        if line:
            wrapped = line > self.state.cursor_line
            self._push_jump()
            self.state.cursor_line = line
            self._refresh()
            if wrapped:
                self._show_transient("Wrapped to last thread", "info", 1.2)
        else:
            self._show_transient("No threads")

    def _seq_next_unread(self) -> None:
        line = self.state.next_unread_thread()
        if line:
            self._push_jump()
            self.state.cursor_line = line
            self._refresh()
        else:
            self._show_transient("No unread replies")

    def _seq_prev_unread(self) -> None:
        line = self.state.prev_unread_thread()
        if line:
            self._push_jump()
            self.state.cursor_line = line
            self._refresh()
        else:
            self._show_transient("No unread replies")

    def _navigate_hunk(self, forward: bool) -> None:
        if self._diff_state is None or not self._diff_state.has_diff():
            self._show_transient("No diff available", "warning")
            return
        wrapped = False
        if forward:
            target = self._diff_state.next_hunk(self.state.cursor_line)
            if target is None:
                target = self._diff_state.next_hunk(0)
                if target is None:
                    return
                wrapped = True
                self._show_transient("Wrapped to first change", "info", 1.2)
        else:
            target = self._diff_state.prev_hunk(self.state.cursor_line)
            if target is None:
                target = self._diff_state.prev_hunk(self.state.line_count + 1)
                if target is None:
                    return
                wrapped = True
                self._show_transient("Wrapped to last change", "info", 1.2)
        self._push_jump()
        self.state.cursor_line = target
        self._refresh()
        if not wrapped and not self._diff_state.is_added(target - 1):
            self._show_transient("Deletion above", "info", 1.2)

    def _next_hunk(self) -> None:
        self._navigate_hunk(forward=True)

    def _prev_hunk(self) -> None:
        self._navigate_hunk(forward=False)

    def _seq_heading_1_fwd(self) -> None:
        self._jump_heading(1, forward=True)

    def _seq_heading_1_back(self) -> None:
        self._jump_heading(1, forward=False)

    def _seq_heading_2_fwd(self) -> None:
        self._jump_heading(2, forward=True)

    def _seq_heading_2_back(self) -> None:
        self._jump_heading(2, forward=False)

    def _seq_heading_3_fwd(self) -> None:
        self._jump_heading(3, forward=True)

    def _seq_heading_3_back(self) -> None:
        self._jump_heading(3, forward=False)

    def _toggle_wrap(self) -> None:
        self._wrap_enabled = not self._wrap_enabled
        if self.pager_widget:
            self.pager_widget.wrap_width = self.size.width if self._wrap_enabled else 0
            self.pager_widget.invalidate_table_cache()
        self._refresh()
        self._show_transient(f"Line wrap {'on' if self._wrap_enabled else 'off'}", "info")

    def _toggle_line_numbers(self) -> None:
        if self.pager_widget:
            self.pager_widget.show_line_numbers = not self.pager_widget.show_line_numbers
            self.pager_widget.invalidate_table_cache()
        self._refresh()
        show = self.pager_widget.show_line_numbers if self.pager_widget else True
        self._show_transient(f"Line numbers {'on' if show else 'off'}", "info")

    def _toggle_diff(self) -> None:
        if self._diff_state is None:
            self._show_transient("No diff available", "warning")
            return
        active = self._diff_state.toggle()
        if self.pager_widget:
            self.pager_widget.diff_state = self._diff_state
            self.pager_widget.refresh_content()
        self._show_transient(f"Diff view {'on' if active else 'off'}")

    def _jump_heading(self, level: int, forward: bool) -> None:
        line = (self._heading_index.next_heading(level, self.state.cursor_line)
                if forward else
                self._heading_index.prev_heading(level, self.state.cursor_line))
        if line:
            self._push_jump()
            self.state.cursor_line = line
            self._refresh()
            self._scroll_to_cursor(center=True)
        else:
            self._show_transient(f"No h{level} headings")

    # --- Overlays ---

    def _open_comment(self) -> None:
        thread = self.state.thread_at_line(self.state.cursor_line)

        def on_submit(text: str) -> None:
            nonlocal thread
            if thread:
                self.state.reply_to_thread(thread.id, text)
                self.state.mark_read(thread.id)
                self._write_event(LiveEvent(
                    type="reply", thread_id=thread.id,
                    author="reviewer", text=text, ts=int(time.time() * 1000),
                ))
            else:
                new_thread = self.state.add_comment(self.state.cursor_line, text)
                self._write_event(LiveEvent(
                    type="comment", thread_id=new_thread.id,
                    line=self.state.cursor_line, author="reviewer",
                    text=text, ts=int(time.time() * 1000),
                ))
                thread = new_thread  # Subsequent submits are replies
                screen.existing_thread = new_thread  # Update for live watcher identification
                screen.update_title(new_thread.id, self.state.cursor_line)
            self._refresh()

        def on_resolve() -> None:
            if thread:
                was_resolved = thread.status == "resolved"
                self.state.resolve_thread(thread.id)
                self.state.mark_read(thread.id)
                event_type = "unresolve" if was_resolved else "resolve"
                self._write_event(LiveEvent(
                    type=event_type, thread_id=thread.id,
                    author="reviewer", ts=int(time.time() * 1000),
                ))
                screen.update_status(thread.status)
            self._refresh()

        # Get spec line text for context preview
        idx = self.state.cursor_line - 1
        spec_line_text = self.state.spec_lines[idx] if 0 <= idx < len(self.state.spec_lines) else ""
        screen = CommentScreen(
            self.state.cursor_line, thread,
            on_submit=on_submit, on_resolve=on_resolve,
            spec_line_text=spec_line_text,
        )

        def on_result(result: CommentResult) -> None:
            if thread:
                self.state.mark_read(thread.id)
            self._refresh()

        self.push_screen(screen, on_result)

    def _open_thread_list(self) -> None:
        def on_resolve(thread_id: str) -> None:
            t = next((t for t in self.state.threads if t.id == thread_id), None)
            if not t:
                return
            was_resolved = t.status == "resolved"
            self.state.resolve_thread(thread_id)
            self.state.mark_read(thread_id)
            event_type = "unresolve" if was_resolved else "resolve"
            self._write_event(LiveEvent(
                type=event_type, thread_id=thread_id, author="reviewer",
                ts=int(time.time() * 1000),
            ))
            self._refresh()

        screen = ThreadListScreen(self.state.threads, on_resolve=on_resolve, unread_ids=set(self.state._unread_thread_ids))

        def on_result(line: int | None) -> None:
            if line is not None:
                self._push_jump()
                self.state.cursor_line = line
                self._refresh()
                self._open_comment()
            else:
                self._refresh()

        self.push_screen(screen, on_result)

    def _resolve_current(self) -> None:
        thread = self.state.thread_at_line(self.state.cursor_line)
        if not thread:
            self._show_transient("No thread on this line")
            return
        was_resolved = thread.status == "resolved"
        self.state.resolve_thread(thread.id)
        self.state.mark_read(thread.id)
        event_type = "unresolve" if was_resolved else "resolve"
        self._write_event(LiveEvent(
            type=event_type, thread_id=thread.id,
            author="reviewer", ts=int(time.time() * 1000),
        ))
        self._refresh()
        action = "Reopened" if was_resolved else "Resolved"
        self._show_transient(f"{action} thread #{thread.id}", "success")

    def _delete_thread(self) -> None:
        thread = self.state.thread_at_line(self.state.cursor_line)
        if not thread:
            self._show_transient("No thread on this line")
            return
        screen = ConfirmScreen("Delete Thread", f"Delete thread #{thread.id} on line {thread.line}?")

        def on_result(confirmed: bool) -> None:
            if confirmed:
                self.state.delete_thread(thread.id)
                self._write_event(LiveEvent(
                    type="delete", thread_id=thread.id,
                    author="reviewer", ts=int(time.time() * 1000),
                ))
                self._refresh()
                self._show_transient(f"Deleted thread #{thread.id}", "success")

        self.push_screen(screen, on_result)

    def _open_search(self) -> None:
        def on_preview(query: str | None) -> None:
            self.search_query = query
            self._refresh()

        screen = SearchScreen(
            self.state.spec_lines, self.state.cursor_line, on_preview=on_preview,
        )

        def on_result(result: tuple[str, int, int] | None) -> None:
            if result:
                query, line, total = result
                self.search_query = query
                self._push_jump()
                self.state.cursor_line = line
                self._show_transient(f"/{query}  [1 of {total}]", "info")
            else:
                self.search_query = None
            self._refresh()

        self.push_screen(screen, on_result)

    def _search_next(self, direction: int) -> None:
        if not self.search_query:
            self._show_transient("No active search \u2014 use / to search")
            return
        q, case_sensitive = smartcase_prepare(self.search_query)
        total = self.state.line_count
        for offset in range(1, total + 1):
            i = (self.state.cursor_line - 1 + offset * direction) % total
            line = self.state.spec_lines[i] if case_sensitive else self.state.spec_lines[i].lower()
            if q in line:
                match_line = i + 1
                wrapped = (direction == 1 and match_line <= self.state.cursor_line) or \
                          (direction == -1 and match_line >= self.state.cursor_line)
                self._push_jump()
                self.state.cursor_line = match_line
                self._refresh()
                self._scroll_to_cursor(margin=self.search_scroll_margin)
                if wrapped:
                    msg = "Search wrapped to top" if direction == 1 else "Search wrapped to bottom"
                    self._show_transient(msg, "info", 1.2)
                return
        self._show_transient(f"Pattern not found: '{self.search_query}'", "warn")
        self._refresh()

    def _is_watcher_running(self) -> bool:
        return is_watcher_running(self.spec_file)

    def _submit(self) -> None:
        if not self.state.threads:
            self._show_transient("No threads to submit.")
            return
        if not self._is_watcher_running():
            self._show_transient("No watcher running. Start 'revspec watch' first.", "warn", 3.0)
            return

        def do_submit() -> None:
            self._write_event(LiveEvent(
                type="submit", author="reviewer", ts=int(time.time() * 1000),
            ))
            count = len(self.state.threads)
            # Start polling spec mtime for reload
            self._spec_poll_timer = self.set_interval(0.5, self._check_spec_reload)
            # Show spinner modal
            spinner = SpinnerScreen(count)

            def on_spinner_done(result: str) -> None:
                if result == "cancel":
                    # User cancelled — stop polling silently
                    if self._spec_poll_timer:
                        self._spec_poll_timer.stop()
                        self._spec_poll_timer = None
                elif result == "timeout":
                    # Timed out — stop polling and warn
                    if self._spec_poll_timer:
                        self._spec_poll_timer.stop()
                        self._spec_poll_timer = None
                    self._show_transient("AI did not update the spec. Press S to resubmit.", "warn", 3.0)
                elif result == "success":
                    self._refresh()
                    self._show_transient("Spec rewritten \u2014 review cleared", "success", 2.5)

            self.push_screen(spinner, on_spinner_done)

        # Unresolved gate
        if not self.state.can_approve():
            open_c, pending = self.state.active_thread_count()
            total = open_c + pending
            screen = ConfirmScreen(
                "Unresolved Threads",
                f"{total} thread(s) still unresolved. Resolve all and continue?",
            )

            def on_confirm(confirmed: bool) -> None:
                if confirmed:
                    for t in self.state.threads:
                        if t.status not in ("resolved", "outdated"):
                            self._write_event(LiveEvent(
                                type="resolve", thread_id=t.id,
                                author="reviewer", ts=int(time.time() * 1000),
                            ))
                    self.state.resolve_all()
                    self._refresh()
                    do_submit()

            self.push_screen(screen, on_confirm)
        else:
            do_submit()

    def _approve(self) -> None:
        if not self.state.can_approve():
            open_c, pending = self.state.active_thread_count()
            total = open_c + pending
            screen = ConfirmScreen(
                "Unresolved Threads",
                f"{total} thread(s) still unresolved. Resolve all and continue?",
            )

            def on_result(confirmed: bool) -> None:
                if confirmed:
                    for t in self.state.threads:
                        if t.status not in ("resolved", "outdated"):
                            self._write_event(LiveEvent(
                                type="resolve", thread_id=t.id,
                                author="reviewer", ts=int(time.time() * 1000),
                            ))
                    self.state.resolve_all()
                    self._exit_tui("approve")

            self.push_screen(screen, on_result)
        else:
            self._exit_tui("approve")

    def _open_command_mode(self) -> None:
        """Simple inline command input."""
        screen = CommandScreen()

        def on_result(cmd: str | None) -> None:
            if cmd is None:
                return
            self._process_command(cmd)

        self.push_screen(screen, on_result)

    def _process_command(self, cmd: str) -> None:
        result = parse_command(cmd)

        if result.action == "force_quit":
            self._exit_tui("session-end")
        elif result.action == "quit":
            open_c, pending = self.state.active_thread_count()
            if open_c + pending > 0:
                self._show_transient(f"{open_c + pending} unresolved thread(s). Use :q! to force quit", "warn", 2.0)
            else:
                self._exit_tui("session-end")
        elif result.action == "submit":
            self._submit()
        elif result.action == "approve":
            self._approve()
        elif result.action == "help":
            self.push_screen(HelpScreen())
        elif result.action == "resolve":
            self._resolve_current()
        elif result.action == "reload":
            self._reload_spec()
        elif result.action == "wrap":
            self._toggle_wrap()
        elif result.action == "diff":
            self._toggle_diff()
        elif result.action == "goto":
            self._push_jump()
            self.state.cursor_line = min(result.args["line"], self.state.line_count)
            self._refresh()
        elif result.action == "unknown":
            self._show_transient(f"Unknown command: {cmd}", "warn")

    def _exit_tui(self, event_type: str) -> None:
        self._write_event(LiveEvent(
            type=event_type, author="reviewer", ts=int(time.time() * 1000),
        ))
        # Clean up offset file if no watcher is running to handle it
        if not self._is_watcher_running():
            base = Path(self.spec_file)
            offset_path = base.parent / (base.stem + ".review.offset")
            try:
                offset_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._diff_state = None
        if self.pager_widget:
            self.pager_widget.diff_state = None
        self.exit()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
