"""Tests for ReviewState."""
import pytest
from revspec_tui.state import ReviewState
from revspec_tui.protocol import Thread, Message


def _make_state(n_lines=20):
    return ReviewState([f"line {i}" for i in range(n_lines)])


def _add_thread(state, line, status="open", unread=False):
    t = state.add_comment(line, f"comment on {line}")
    t.status = status
    if unread:
        state._unread_thread_ids.add(t.id)
    return t


class TestResolveAllPending:
    def test_resolves_only_pending(self):
        state = _make_state()
        t1 = _add_thread(state, 1, status="open")
        t2 = _add_thread(state, 5, status="pending")
        t3 = _add_thread(state, 10, status="resolved")
        state.resolve_all_pending()
        assert t1.status == "open"
        assert t2.status == "resolved"
        assert t3.status == "resolved"

    def test_noop_when_no_pending(self):
        state = _make_state()
        _add_thread(state, 1, status="open")
        state.resolve_all_pending()
        assert state.threads[0].status == "open"


class TestNextUnreadThread:
    def test_finds_next_after_cursor(self):
        state = _make_state()
        _add_thread(state, 3, unread=True)
        _add_thread(state, 8, unread=True)
        state.cursor_line = 1
        assert state.next_unread_thread() == 3

    def test_wraps_around(self):
        state = _make_state()
        _add_thread(state, 3, unread=True)
        state.cursor_line = 10
        assert state.next_unread_thread() == 3

    def test_returns_none_when_no_unread(self):
        state = _make_state()
        _add_thread(state, 3, status="open")
        state.cursor_line = 1
        assert state.next_unread_thread() is None


class TestPrevUnreadThread:
    def test_finds_prev_before_cursor(self):
        state = _make_state()
        _add_thread(state, 3, unread=True)
        _add_thread(state, 8, unread=True)
        state.cursor_line = 10
        assert state.prev_unread_thread() == 8

    def test_wraps_around(self):
        state = _make_state()
        _add_thread(state, 8, unread=True)
        state.cursor_line = 3
        assert state.prev_unread_thread() == 8

    def test_returns_none_when_no_unread(self):
        state = _make_state()
        state.cursor_line = 5
        assert state.prev_unread_thread() is None
