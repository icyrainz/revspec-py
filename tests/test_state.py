"""Tests for ReviewState."""
from revspec.state import ReviewState


def _make_state(n_lines=20):
    return ReviewState([f"line {i}" for i in range(n_lines)])


def _add_thread(state, line, status="open", unread=False):
    t = state.add_comment(line, f"comment on {line}")
    t.status = status
    if unread:
        state._unread_thread_ids.add(t.id)
    return t


# --- Basic properties ---

class TestBasicProperties:
    def test_line_count(self):
        state = _make_state(10)
        assert state.line_count == 10

    def test_initial_cursor(self):
        state = _make_state()
        assert state.cursor_line == 1

    def test_initial_no_threads(self):
        state = _make_state()
        assert state.threads == []

    def test_unread_count_zero(self):
        state = _make_state()
        assert state.unread_count == 0


# --- add_comment ---

class TestAddComment:
    def test_creates_thread(self):
        state = _make_state()
        t = state.add_comment(5, "Fix this")
        assert t.line == 5
        assert t.status == "open"
        assert len(t.messages) == 1
        assert t.messages[0].author == "reviewer"
        assert t.messages[0].text == "Fix this"

    def test_thread_id_is_8_chars(self):
        state = _make_state()
        t = state.add_comment(1, "test")
        assert len(t.id) == 8
        assert t.id.isalnum()

    def test_adds_to_threads_list(self):
        state = _make_state()
        state.add_comment(1, "A")
        state.add_comment(5, "B")
        assert len(state.threads) == 2


# --- reply_to_thread ---

class TestReplyToThread:
    def test_appends_message(self):
        state = _make_state()
        t = state.add_comment(5, "Fix this")
        state.reply_to_thread(t.id, "Done")
        assert len(t.messages) == 2
        assert t.messages[1].text == "Done"
        assert t.messages[1].author == "reviewer"

    def test_sets_status_open(self):
        state = _make_state()
        t = state.add_comment(5, "Fix")
        t.status = "resolved"
        state.reply_to_thread(t.id, "Actually no")
        assert t.status == "open"

    def test_nonexistent_thread_noop(self):
        state = _make_state()
        state.reply_to_thread("nonexistent", "Hello")  # Should not raise


# --- resolve_thread ---

class TestResolveThread:
    def test_resolves_open(self):
        state = _make_state()
        t = state.add_comment(5, "Fix")
        state.resolve_thread(t.id)
        assert t.status == "resolved"

    def test_unresolves_resolved(self):
        state = _make_state()
        t = state.add_comment(5, "Fix")
        t.status = "resolved"
        state.resolve_thread(t.id)
        assert t.status == "open"

    def test_nonexistent_thread_noop(self):
        state = _make_state()
        state.resolve_thread("nonexistent")  # Should not raise


# --- resolve_all ---

class TestResolveAll:
    def test_resolves_all_open(self):
        state = _make_state()
        t1 = _add_thread(state, 1, status="open")
        t2 = _add_thread(state, 5, status="pending")
        t3 = _add_thread(state, 10, status="resolved")
        state.resolve_all()
        assert t1.status == "resolved"
        assert t2.status == "resolved"
        assert t3.status == "resolved"  # already resolved, stays

    def test_skips_outdated(self):
        state = _make_state()
        t = _add_thread(state, 1, status="outdated")
        state.resolve_all()
        assert t.status == "outdated"


# --- resolve_all_pending ---

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


# --- delete_thread ---

class TestDeleteThread:
    def test_removes_thread(self):
        state = _make_state()
        t = state.add_comment(5, "Fix")
        state.delete_thread(t.id)
        assert len(state.threads) == 0

    def test_removes_unread_tracking(self):
        state = _make_state()
        t = _add_thread(state, 5, unread=True)
        assert state.unread_count == 1
        state.delete_thread(t.id)
        assert state.unread_count == 0

    def test_nonexistent_noop(self):
        state = _make_state()
        state.add_comment(5, "Fix")
        state.delete_thread("nonexistent")
        assert len(state.threads) == 1


# --- thread_at_line ---

class TestThreadAtLine:
    def test_finds_thread(self):
        state = _make_state()
        t = state.add_comment(5, "Fix")
        assert state.thread_at_line(5) is t

    def test_returns_none_no_thread(self):
        state = _make_state()
        assert state.thread_at_line(5) is None


# --- next_thread / prev_thread ---

class TestNextPrevThread:
    def test_next_thread(self):
        state = _make_state()
        _add_thread(state, 3)
        _add_thread(state, 8)
        state.cursor_line = 1
        assert state.next_thread() == 3

    def test_next_thread_wraps(self):
        state = _make_state()
        _add_thread(state, 3)
        state.cursor_line = 10
        assert state.next_thread() == 3

    def test_prev_thread(self):
        state = _make_state()
        _add_thread(state, 3)
        _add_thread(state, 8)
        state.cursor_line = 10
        assert state.prev_thread() == 8

    def test_prev_thread_wraps(self):
        state = _make_state()
        _add_thread(state, 8)
        state.cursor_line = 3
        assert state.prev_thread() == 8

    def test_no_threads(self):
        state = _make_state()
        assert state.next_thread() is None
        assert state.prev_thread() is None


# --- next_unread_thread / prev_unread_thread ---

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


# --- heading navigation ---

class TestHeadingNavigation:
    def _heading_state(self):
        lines = [
            "# Heading 1",
            "Some text",
            "## Heading 2",
            "More text",
            "### Heading 3",
            "Even more",
            "# Another H1",
        ]
        return ReviewState(lines)

    def test_next_h1(self):
        state = self._heading_state()
        state.cursor_line = 2  # after first h1
        assert state.next_heading(1) == 7  # "# Another H1"

    def test_next_h1_wraps(self):
        state = self._heading_state()
        state.cursor_line = 7
        assert state.next_heading(1) == 1

    def test_prev_h1(self):
        state = self._heading_state()
        state.cursor_line = 7
        assert state.prev_heading(1) == 1

    def test_next_h2(self):
        state = self._heading_state()
        state.cursor_line = 1
        assert state.next_heading(2) == 3

    def test_h2_does_not_match_h3(self):
        state = self._heading_state()
        state.cursor_line = 4
        # After "## Heading 2", next h2 should wrap, not match h3
        result = state.next_heading(2)
        assert result == 3  # wraps back to the only h2

    def test_no_headings_returns_none(self):
        state = _make_state()  # "line 0", "line 1", etc.
        assert state.next_heading(1) is None
        assert state.prev_heading(1) is None


# --- can_approve ---

class TestCanApprove:
    def test_no_threads(self):
        state = _make_state()
        assert state.can_approve() is True

    def test_all_resolved(self):
        state = _make_state()
        _add_thread(state, 1, status="resolved")
        _add_thread(state, 5, status="resolved")
        assert state.can_approve() is True

    def test_open_thread_blocks(self):
        state = _make_state()
        _add_thread(state, 1, status="open")
        assert state.can_approve() is False

    def test_pending_thread_blocks(self):
        state = _make_state()
        _add_thread(state, 1, status="pending")
        assert state.can_approve() is False

    def test_outdated_does_not_block(self):
        state = _make_state()
        _add_thread(state, 1, status="outdated")
        assert state.can_approve() is True


# --- active_thread_count ---

class TestActiveThreadCount:
    def test_counts(self):
        state = _make_state()
        _add_thread(state, 1, status="open")
        _add_thread(state, 3, status="open")
        _add_thread(state, 5, status="pending")
        _add_thread(state, 7, status="resolved")
        open_c, pending = state.active_thread_count()
        assert open_c == 2
        assert pending == 1

    def test_no_threads(self):
        state = _make_state()
        open_c, pending = state.active_thread_count()
        assert open_c == 0
        assert pending == 0


# --- add_owner_reply ---

class TestAddOwnerReply:
    def test_adds_message_sets_pending(self):
        state = _make_state()
        t = state.add_comment(5, "Fix this")
        state.add_owner_reply(t.id, "Done", ts=2000)
        assert len(t.messages) == 2
        assert t.messages[1].author == "owner"
        assert t.messages[1].text == "Done"
        assert t.status == "pending"

    def test_marks_unread(self):
        state = _make_state()
        t = state.add_comment(5, "Fix this")
        state.add_owner_reply(t.id, "Done")
        assert state.is_unread(t.id)
        assert state.unread_count == 1


# --- delete_last_draft_message ---

class TestDeleteLastDraftMessage:
    def test_removes_last_reviewer_message(self):
        state = _make_state()
        t = state.add_comment(5, "First")
        state.reply_to_thread(t.id, "Second")
        state.delete_last_draft_message(t.id)
        assert len(t.messages) == 1
        assert t.messages[0].text == "First"

    def test_removes_thread_if_empty(self):
        state = _make_state()
        t = state.add_comment(5, "Only message")
        state.delete_last_draft_message(t.id)
        assert len(state.threads) == 0

    def test_noop_for_nonexistent_thread(self):
        state = _make_state()
        state.delete_last_draft_message("nonexistent")  # Should not raise

    def test_does_not_remove_owner_messages(self):
        state = _make_state()
        t = state.add_comment(5, "My comment")
        state.add_owner_reply(t.id, "AI response")
        state.delete_last_draft_message(t.id)
        # Should remove "My comment" (last reviewer msg), not "AI response"
        assert len(t.messages) == 1
        assert t.messages[0].author == "owner"


# --- mark_read ---

class TestMarkRead:
    def test_clears_unread(self):
        state = _make_state()
        t = _add_thread(state, 5, unread=True)
        assert state.is_unread(t.id)
        state.mark_read(t.id)
        assert not state.is_unread(t.id)
        assert state.unread_count == 0

    def test_noop_if_not_unread(self):
        state = _make_state()
        t = state.add_comment(5, "Fix")
        state.mark_read(t.id)  # Should not raise


# --- reset ---

class TestReset:
    def test_clears_everything(self):
        state = _make_state()
        _add_thread(state, 5, unread=True)
        state.cursor_line = 10
        new_lines = ["new line 1", "new line 2"]
        state.reset(new_lines)
        assert state.spec_lines == new_lines
        assert state.line_count == 2
        assert state.threads == []
        assert state.cursor_line == 1
        assert state.unread_count == 0
