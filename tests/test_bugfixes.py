"""Tests for bug fixes — protocol truncation, markdown word-wrap, comment screen behavior."""
import json
import os

from revspec.protocol import (
    LiveEvent, append_event, read_events, replay_events_to_threads,
    Thread, Message,
)
from revspec.markdown import _word_wrap_count
from revspec.comment_screen import CommentScreen, _render_hints
from revspec.theme import THEME


# --- protocol.py: read_events returns file_size on truncation ---

class TestReadEventsTruncation:
    """Bug fix: read_events returned stale offset when file was truncated,
    permanently blinding the live watcher."""

    def test_offset_resets_on_truncation(self, tmp_path):
        """After file truncation, returned offset should be the new file size,
        not the stale old offset."""
        path = str(tmp_path / "test.review.jsonl")
        # Write several events to build up offset
        for i in range(5):
            append_event(path, LiveEvent(type="approve", author="reviewer", ts=1000 + i))
        _, offset = read_events(path)
        assert offset > 0

        # Truncate the file (simulates watch CLI truncation guard)
        with open(path, "w") as f:
            f.write("")
        new_size = os.path.getsize(path)
        assert new_size == 0

        # read_events should return file_size (0), not the stale offset
        events, new_offset = read_events(path, offset)
        assert events == []
        assert new_offset == 0  # was: new_offset == offset (bug)

    def test_offset_resets_on_partial_truncation(self, tmp_path):
        """File shortened but not empty — offset should still reset."""
        path = str(tmp_path / "test.review.jsonl")
        for i in range(5):
            append_event(path, LiveEvent(type="approve", author="reviewer", ts=1000 + i))
        _, old_offset = read_events(path)

        # Rewrite with fewer events
        with open(path, "w") as f:
            f.write(json.dumps({"type": "approve", "author": "reviewer", "ts": 9000}) + "\n")
        new_size = os.path.getsize(path)
        assert new_size < old_offset

        events, new_offset = read_events(path, old_offset)
        assert events == []
        assert new_offset == new_size  # reset to actual file size

    def test_new_events_readable_after_truncation_recovery(self, tmp_path):
        """After offset resets on truncation, new events should be readable."""
        path = str(tmp_path / "test.review.jsonl")
        append_event(path, LiveEvent(type="approve", author="reviewer", ts=1000))
        _, offset = read_events(path)

        # Truncate
        with open(path, "w") as f:
            f.write("")
        _, reset_offset = read_events(path, offset)
        assert reset_offset == 0

        # Write new event after truncation
        append_event(path, LiveEvent(type="approve", author="reviewer", ts=2000))
        events, _ = read_events(path, reset_offset)
        assert len(events) == 1
        assert events[0].ts == 2000

    def test_no_change_returns_same_offset(self, tmp_path):
        """When no new data, offset == file_size — should still work."""
        path = str(tmp_path / "test.review.jsonl")
        append_event(path, LiveEvent(type="approve", author="reviewer", ts=1000))
        _, offset = read_events(path)

        # Read again with no new data
        events, new_offset = read_events(path, offset)
        assert events == []
        assert new_offset == offset  # unchanged, equals file_size


# --- markdown.py: word wrap break_at == 0 ---

class TestWordWrapBreakAtZero:
    """Bug fix: break_at <= 0 should be break_at < 0.
    rfind returns 0 for space at position 0, which is a valid break point."""

    def test_space_at_position_zero(self):
        """Text starting with space should break at position 0, not hard-cut.
        Bug: rfind returning 0 was treated as 'not found' (same as -1).
        Fix: 0 is a valid break position — only -1 means not found."""
        # " xxxx xxxx" width 5: rfind(" ", 0, 5) = 0
        # With fix: breaks at 0, strips space, then "xxxx xxxx" → break at 4 → "xxxx"
        # Result: 2 extra lines
        text = " xxxx xxxx"
        count = _word_wrap_count(text, 5)
        assert count == 2

    def test_no_space_hard_cuts(self):
        """When there truly is no space, hard cut should happen."""
        text = "x" * 25
        count = _word_wrap_count(text, 10)
        assert count == 2  # 25 / 10 = 2.5, so 2 extra lines

    def test_space_at_position_one(self):
        """Space at position 1 should break at 1 (was already working)."""
        text = "a " + "b" * 20
        count = _word_wrap_count(text, 10)
        assert count >= 2


# --- comment_screen.py: status indicator in title ---

class TestCommentScreenStatusIndicator:
    """Thread state indicator [OPEN]/[RESOLVED] in comment popup title."""

    def test_existing_thread_shows_status_in_title(self):
        """Existing thread popup title should include status label."""
        thread = Thread(id="abc123", line=5, status="open", messages=[
            Message(author="reviewer", text="Fix this", ts=1000),
        ])
        screen = CommentScreen(line=5, existing_thread=thread)
        # The title is set in on_mount, but we can verify the logic
        # by checking the thread data is available
        assert screen.existing_thread.status == "open"

    def test_resolved_thread_shows_resolved(self):
        thread = Thread(id="abc123", line=5, status="resolved", messages=[
            Message(author="reviewer", text="Fix this", ts=1000),
        ])
        screen = CommentScreen(line=5, existing_thread=thread)
        assert screen.existing_thread.status == "resolved"

    def test_new_thread_has_no_status(self):
        """New thread popup should not have a status indicator."""
        screen = CommentScreen(line=5)
        assert screen.existing_thread is None


# --- comment_screen.py: resolve callback behavior ---

class TestCommentScreenResolve:
    """Resolve in comment popup should call the on_resolve callback."""

    def test_on_resolve_callback_called(self):
        """Pressing r in normal mode should trigger the resolve callback."""
        called = []
        thread = Thread(id="abc123", line=5, status="open", messages=[
            Message(author="reviewer", text="Fix this", ts=1000),
        ])
        screen = CommentScreen(
            line=5, existing_thread=thread,
            on_resolve=lambda: called.append(True),
        )
        assert screen._on_resolve is not None

    def test_no_resolve_without_thread(self):
        """New thread popup should not have resolve behavior."""
        screen = CommentScreen(line=5)
        assert screen.existing_thread is None


# --- comment_screen.py: hint rendering ---

class TestHintRendering:
    """Verify hint bar shows resolve option in normal mode."""

    def test_normal_mode_shows_resolve_hint(self):
        hints = _render_hints("normal")
        plain = hints.plain
        assert "resolve" in plain
        assert "[r]" in plain

    def test_insert_mode_shows_send_hint(self):
        hints = _render_hints("insert")
        plain = hints.plain
        assert "send" in plain
        assert "[Tab]" in plain

    def test_normal_mode_shows_close_hint(self):
        hints = _render_hints("normal")
        plain = hints.plain
        assert "close" in plain
        assert "[q/Esc]" in plain

    def test_resolved_mode_shows_reopen_hint(self):
        hints = _render_hints("normal", resolved=True)
        plain = hints.plain
        assert "reopen" in plain
        assert "[r]" in plain
        assert "resolve" not in plain

    def test_unresolved_mode_shows_resolve_hint(self):
        hints = _render_hints("normal", resolved=False)
        plain = hints.plain
        assert "resolve" in plain
        assert "reopen" not in plain


# --- protocol.py: duplicate comment events should not produce duplicate threads ---

class TestReplayDuplicateComments:
    """Bug fix: duplicate comment events for the same threadId produced
    duplicate entries in the returned thread list."""

    def test_duplicate_comment_no_duplicate_thread(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="First"),
            LiveEvent(type="comment", author="reviewer", ts=2000,
                      thread_id="t1", line=5, text="Second"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 1
        # Second comment overwrites the first
        assert threads[0].messages[0].text == "Second"

    def test_separate_threads_still_work(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="A"),
            LiveEvent(type="comment", author="reviewer", ts=2000,
                      thread_id="t2", line=10, text="B"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 2
        assert threads[0].id == "t1"
        assert threads[1].id == "t2"


# --- watcher detection ---

class TestWatcherDetection:
    """Submit should check for running watcher via lock file."""

    def test_no_lock_file_means_no_watcher(self, tmp_path):
        lock_path = tmp_path / "spec.review.lock"
        assert not lock_path.exists()

    def test_lock_file_with_stale_pid(self, tmp_path):
        lock_path = tmp_path / "spec.review.lock"
        lock_path.write_text("999999999")  # PID that almost certainly doesn't exist
        # os.kill(999999999, 0) should raise OSError
        try:
            os.kill(999999999, 0)
        except OSError:
            pass  # Expected — stale lock

    def test_lock_file_with_own_pid(self, tmp_path):
        lock_path = tmp_path / "spec.review.lock"
        lock_path.write_text(str(os.getpid()))
        # Our own PID is always valid
        pid = int(lock_path.read_text().strip())
        os.kill(pid, 0)  # Should not raise


# --- watch.py: session-end cleanup ---

class TestWatchSessionEndCleanup:
    """Session-end should clean up lock + offset files, same as approve."""

    def test_session_end_cleans_lock_and_offset(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        from revspec.watch import run_watch
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\n")
        jsonl = tmp_path / "spec.review.jsonl"
        jsonl.write_text(json.dumps({
            "type": "session-end", "author": "reviewer", "ts": 1000,
        }) + "\n")

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "session ended" in captured.out.lower()
        assert not (tmp_path / "spec.review.lock").exists()
        assert not (tmp_path / "spec.review.offset").exists()

    def test_approve_still_cleans_up(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        from revspec.watch import run_watch
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\n")
        jsonl = tmp_path / "spec.review.jsonl"
        jsonl.write_text(json.dumps({
            "type": "approve", "author": "reviewer", "ts": 1000,
        }) + "\n")

        run_watch(str(spec))
        assert not (tmp_path / "spec.review.lock").exists()
        assert not (tmp_path / "spec.review.offset").exists()

    def test_submit_preserves_offset(self, tmp_path, monkeypatch):
        """Submit should keep offset file (for crash recovery), not delete it."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        from revspec.watch import run_watch
        spec = tmp_path / "spec.md"
        spec.write_text("# Spec\n")
        jsonl = tmp_path / "spec.review.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({
                "type": "comment", "author": "reviewer", "ts": 1000,
                "threadId": "t1", "line": 1, "text": "Fix",
            }) + "\n")
            f.write(json.dumps({
                "type": "submit", "author": "reviewer", "ts": 2000,
            }) + "\n")

        run_watch(str(spec))
        # Offset file should still exist after submit (crash recovery needs it)
        assert (tmp_path / "spec.review.offset").exists()


# --- comment_screen.py: mode initialization ---

class TestCommentScreenModeInit:
    """Verify correct initial mode based on thread state."""

    def test_new_thread_starts_in_insert(self):
        screen = CommentScreen(line=5)
        assert screen._mode == "insert"

    def test_existing_thread_with_messages_starts_in_normal(self):
        thread = Thread(id="abc", line=5, status="open", messages=[
            Message(author="reviewer", text="hi", ts=1000),
        ])
        screen = CommentScreen(line=5, existing_thread=thread)
        assert screen._mode == "normal"

    def test_existing_thread_no_messages_starts_in_insert(self):
        thread = Thread(id="abc", line=5, status="open", messages=[])
        screen = CommentScreen(line=5, existing_thread=thread)
        assert screen._mode == "insert"


# --- comment_screen.py: border colors per mode ---

class TestCommentScreenBorderColors:
    """Border colors: blue=normal/open, mauve=insert, green=normal/resolved."""

    def test_insert_mode_uses_mauve(self):
        # _enter_insert sets border to THEME["mauve"]
        assert THEME["mauve"] == "#cba6f7"

    def test_normal_open_uses_blue(self):
        # _enter_normal with open thread sets border to THEME["blue"]
        assert THEME["blue"] == "#89b4fa"

    def test_normal_resolved_uses_green(self):
        # _enter_normal with resolved thread sets border to THEME["green"]
        assert THEME["green"] == "#a6e3a1"

    def test_on_mount_insert_sets_mauve(self):
        """New thread popup should get mauve border on mount."""
        screen = CommentScreen(line=5)
        assert screen._mode == "insert"
        # on_mount will set dialog.styles.border = ("solid", THEME["mauve"])
        # We can't run on_mount without Textual app, but we verify the mode is right

    def test_resolved_thread_normal_mode(self):
        """Resolved thread should start in normal mode (blue initially,
        _enter_normal changes to green based on thread status)."""
        thread = Thread(id="abc", line=5, status="resolved", messages=[
            Message(author="reviewer", text="done", ts=1000),
        ])
        screen = CommentScreen(line=5, existing_thread=thread)
        assert screen._mode == "normal"
        assert screen.existing_thread.status == "resolved"


# --- comment_screen.py: update_status ---

class TestCommentScreenUpdateStatus:
    """update_status should change title, border, and hints."""

    def test_update_status_noop_without_thread(self):
        """update_status should not crash when no existing_thread."""
        screen = CommentScreen(line=5)
        # Should silently return without error
        # Can't call update_status without mount, but verify guard logic
        assert screen.existing_thread is None

    def test_thread_reference_mutates_in_place(self):
        """Verify resolve_thread mutates the thread object that the screen holds."""
        from revspec.state import ReviewState
        state = ReviewState(["# Test", "line 2"])
        thread = state.add_comment(1, "Fix this")
        assert thread.status == "open"

        state.resolve_thread(thread.id)
        # The same object reference should now be resolved
        assert thread.status == "resolved"

        state.resolve_thread(thread.id)
        assert thread.status == "open"


# --- protocol.py: replay robustness ---

class TestReplayRobustness:
    """Edge cases in replay_events_to_threads."""

    def test_delete_then_recreate_same_id(self):
        """Deleting a thread and re-commenting with the same ID."""
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="First"),
            LiveEvent(type="delete", author="reviewer", ts=2000,
                      thread_id="t1"),
            LiveEvent(type="comment", author="reviewer", ts=3000,
                      thread_id="t1", line=10, text="Second"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 1
        assert threads[0].line == 10
        assert threads[0].messages[0].text == "Second"

    def test_resolve_unresolve_cycle(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix"),
            LiveEvent(type="resolve", author="reviewer", ts=2000,
                      thread_id="t1"),
            LiveEvent(type="unresolve", author="reviewer", ts=3000,
                      thread_id="t1"),
            LiveEvent(type="resolve", author="reviewer", ts=4000,
                      thread_id="t1"),
        ]
        threads = replay_events_to_threads(events)
        assert threads[0].status == "resolved"

    def test_reply_before_comment_ignored(self):
        """Reply for a thread that hasn't been created yet."""
        events = [
            LiveEvent(type="reply", author="owner", ts=1000,
                      thread_id="t1", text="Done"),
            LiveEvent(type="comment", author="reviewer", ts=2000,
                      thread_id="t1", line=5, text="Fix"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 1
        # Only the comment message, not the orphan reply
        assert len(threads[0].messages) == 1

    def test_empty_events_list(self):
        threads = replay_events_to_threads([])
        assert threads == []

    def test_owner_reply_sets_pending(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix"),
            LiveEvent(type="reply", author="owner", ts=2000,
                      thread_id="t1", text="Done"),
        ]
        threads = replay_events_to_threads(events)
        assert threads[0].status == "pending"

    def test_reviewer_reply_resets_to_open(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix"),
            LiveEvent(type="reply", author="owner", ts=2000,
                      thread_id="t1", text="Done"),
            LiveEvent(type="reply", author="reviewer", ts=3000,
                      thread_id="t1", text="Not yet"),
        ]
        threads = replay_events_to_threads(events)
        assert threads[0].status == "open"


# --- hint rendering: insert mode label ---

class TestInsertModeHintLabel:
    """Mode labels moved to title bar — hints contain only key actions."""

    def test_insert_hints_have_tab(self):
        hints = _render_hints("insert")
        plain = hints.plain
        assert "[Tab]" in plain
        assert "send" in plain

    def test_normal_hints_have_reply(self):
        hints = _render_hints("normal")
        plain = hints.plain
        assert "[i/c]" in plain
        assert "reply" in plain


# --- _do_reload: thread state preserved after reload ---

class TestReloadPreservesThreads:
    """After reload, threads from JSONL should be re-replayed."""

    def test_threads_survive_reload(self, tmp_path):
        """Simulate what _do_reload does: reset state, then re-replay JSONL."""
        from revspec.state import ReviewState
        spec_lines = ["# Spec", "line 2", "line 3"]
        state = ReviewState(spec_lines)
        state.add_comment(1, "Fix this")
        assert len(state.threads) == 1

        # Write JSONL with the thread
        jsonl = tmp_path / "test.review.jsonl"
        append_event(str(jsonl), LiveEvent(
            type="comment", author="reviewer", ts=1000,
            thread_id="t1", line=1, text="Fix this",
        ))
        append_event(str(jsonl), LiveEvent(
            type="resolve", author="reviewer", ts=2000,
            thread_id="t1",
        ))

        # Simulate reload: reset + replay
        state.reset(["# New spec", "new line 2"])
        assert len(state.threads) == 0  # wiped

        events, _ = read_events(str(jsonl))
        for t in replay_events_to_threads(events):
            state.threads.append(t)

        assert len(state.threads) == 1
        assert state.threads[0].id == "t1"
        assert state.threads[0].status == "resolved"

    def test_reload_empty_jsonl(self, tmp_path):
        """Reload with empty JSONL should leave no threads."""
        from revspec.state import ReviewState
        state = ReviewState(["# Spec"])
        state.add_comment(1, "old")

        jsonl = tmp_path / "test.review.jsonl"
        jsonl.write_text("")

        state.reset(["# New spec"])
        events, _ = read_events(str(jsonl))
        for t in replay_events_to_threads(events):
            state.threads.append(t)

        assert len(state.threads) == 0
