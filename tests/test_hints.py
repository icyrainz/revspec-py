"""Tests for hints.py — status bar and hint bar builders."""

from revspec.hints import build_hints, build_top_bar, build_bottom_bar
from revspec.protocol import Thread, Message


class TestBuildHints:
    def test_single_hint(self):
        text = build_hints([("j/k", "navigate")])
        plain = text.plain
        assert "[j/k]" in plain
        assert "navigate" in plain

    def test_multiple_hints(self):
        text = build_hints([("j/k", "nav"), ("c", "comment"), ("?", "help")])
        plain = text.plain
        assert "[j/k]" in plain
        assert "[c]" in plain
        assert "[?]" in plain

    def test_empty_hints(self):
        text = build_hints([])
        assert text.plain.strip() == ""


def _thread(status="open", messages=None, line=1, tid="t1"):
    t = Thread(id=tid, line=line, status=status, messages=messages or [])
    return t


def _msg(author="reviewer", text="hello"):
    return Message(author=author, text=text, ts=1000)


class TestBuildTopBar:
    def test_file_name(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=0,
            cursor_line=1, line_count=10, spec_lines=["line"] * 10,
            mtime_changed=False,
        )
        assert "spec.md" in text.plain

    def test_thread_progress(self):
        threads = [_thread("resolved"), _thread("open", tid="t2")]
        text = build_top_bar(
            file_name="spec.md", threads=threads, unread_count=0,
            cursor_line=1, line_count=10, spec_lines=["line"] * 10,
            mtime_changed=False,
        )
        assert "1/2 resolved" in text.plain

    def test_all_resolved(self):
        threads = [_thread("resolved"), _thread("resolved", tid="t2")]
        text = build_top_bar(
            file_name="spec.md", threads=threads, unread_count=0,
            cursor_line=1, line_count=10, spec_lines=["line"] * 10,
            mtime_changed=False,
        )
        assert "2/2 resolved" in text.plain

    def test_unread_singular(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=1,
            cursor_line=1, line_count=10, spec_lines=["line"] * 10,
            mtime_changed=False,
        )
        assert "1 new reply" in text.plain

    def test_unread_plural(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=3,
            cursor_line=1, line_count=10, spec_lines=["line"] * 10,
            mtime_changed=False,
        )
        assert "3 new replies" in text.plain

    def test_mtime_changed_warning(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=0,
            cursor_line=1, line_count=10, spec_lines=["line"] * 10,
            mtime_changed=True,
        )
        assert "Spec changed externally" in text.plain

    def test_position_top(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=0,
            cursor_line=1, line_count=100, spec_lines=["line"] * 100,
            mtime_changed=False,
        )
        assert "Top" in text.plain

    def test_position_bottom(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=0,
            cursor_line=100, line_count=100, spec_lines=["line"] * 100,
            mtime_changed=False,
        )
        assert "Bot" in text.plain

    def test_position_percentage(self):
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=0,
            cursor_line=50, line_count=100, spec_lines=["line"] * 100,
            mtime_changed=False,
        )
        assert "49%" in text.plain or "50%" in text.plain

    def test_breadcrumb(self):
        lines = ["# My Section", "text", "more text"]
        text = build_top_bar(
            file_name="spec.md", threads=[], unread_count=0,
            cursor_line=3, line_count=3, spec_lines=lines,
            mtime_changed=False,
        )
        assert "My Section" in text.plain


class TestBuildBottomBar:
    def test_message_info(self):
        text = build_bottom_bar(message="Hello world", icon="info")
        assert "Hello world" in text.plain

    def test_message_warn(self):
        text = build_bottom_bar(message="Warning!", icon="warn")
        assert "Warning!" in text.plain
        assert "!" in text.plain

    def test_message_success(self):
        text = build_bottom_bar(message="Done", icon="success")
        assert "Done" in text.plain

    def test_thread_preview(self):
        t = _thread(messages=[_msg(text="This is the first comment")])
        text = build_bottom_bar(thread=t, has_active_message=False)
        assert "This is the first comment" in text.plain
        assert "[open]" in text.plain

    def test_thread_preview_with_replies(self):
        t = _thread(messages=[_msg(), _msg(author="owner", text="reply")])
        text = build_bottom_bar(thread=t, has_active_message=False)
        assert "1 reply" in text.plain

    def test_thread_preview_truncates_long(self):
        t = _thread(messages=[_msg(text="x" * 100)])
        text = build_bottom_bar(thread=t, has_active_message=False)
        assert "\u2026" in text.plain  # ellipsis

    def test_default_hints_no_thread(self):
        text = build_bottom_bar()
        plain = text.plain
        assert "[j/k]" in plain
        assert "[c]" in plain
        assert "[?]" in plain
        assert "resolve" not in plain

    def test_default_hints_with_thread(self):
        t = _thread()  # empty messages
        text = build_bottom_bar(thread=t)
        assert "resolve" in text.plain

    def test_active_message_suppresses_preview(self):
        t = _thread(messages=[_msg(text="preview text")])
        text = build_bottom_bar(thread=t, has_active_message=True)
        # Should show hints, not preview
        assert "preview text" not in text.plain
