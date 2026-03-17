"""Tests for JSONL protocol — event validation, parsing, serialization, and thread replay."""
import json
from revspec_tui.protocol import (
    LiveEvent,
    is_valid_event, parse_event, append_event,
    read_events, replay_events_to_threads,
)


# --- is_valid_event ---

class TestIsValidEvent:
    def test_valid_comment(self):
        assert is_valid_event({
            "type": "comment", "author": "reviewer", "ts": 1000,
            "threadId": "abc123", "text": "Fix this", "line": 5,
        })

    def test_valid_reply(self):
        assert is_valid_event({
            "type": "reply", "author": "owner", "ts": 2000,
            "threadId": "abc123", "text": "Done",
        })

    def test_valid_resolve(self):
        assert is_valid_event({
            "type": "resolve", "author": "reviewer", "ts": 3000,
            "threadId": "abc123",
        })

    def test_valid_unresolve(self):
        assert is_valid_event({
            "type": "unresolve", "author": "reviewer", "ts": 3000,
            "threadId": "abc123",
        })

    def test_valid_delete(self):
        assert is_valid_event({
            "type": "delete", "author": "reviewer", "ts": 3000,
            "threadId": "abc123",
        })

    def test_valid_approve(self):
        assert is_valid_event({
            "type": "approve", "author": "reviewer", "ts": 4000,
        })

    def test_valid_submit(self):
        assert is_valid_event({
            "type": "submit", "author": "reviewer", "ts": 5000,
        })

    def test_valid_session_end(self):
        assert is_valid_event({
            "type": "session-end", "author": "reviewer", "ts": 6000,
        })

    def test_valid_round(self):
        assert is_valid_event({
            "type": "round", "author": "reviewer", "ts": 7000, "round": 1,
        })

    def test_round_missing_round_field(self):
        assert not is_valid_event({
            "type": "round", "author": "reviewer", "ts": 7000,
        })

    def test_invalid_type(self):
        assert not is_valid_event({
            "type": "bogus", "author": "reviewer", "ts": 1000,
        })

    def test_missing_ts(self):
        assert not is_valid_event({
            "type": "approve", "author": "reviewer",
        })

    def test_missing_author(self):
        assert not is_valid_event({
            "type": "approve", "ts": 1000,
        })

    def test_comment_missing_text(self):
        assert not is_valid_event({
            "type": "comment", "author": "reviewer", "ts": 1000,
            "threadId": "abc123", "line": 5,
        })

    def test_comment_missing_line(self):
        assert not is_valid_event({
            "type": "comment", "author": "reviewer", "ts": 1000,
            "threadId": "abc123", "text": "Fix this",
        })

    def test_comment_missing_thread_id(self):
        assert not is_valid_event({
            "type": "comment", "author": "reviewer", "ts": 1000,
            "text": "Fix this", "line": 5,
        })

    def test_reply_missing_text(self):
        assert not is_valid_event({
            "type": "reply", "author": "owner", "ts": 2000,
            "threadId": "abc123",
        })

    def test_reply_missing_thread_id(self):
        assert not is_valid_event({
            "type": "reply", "author": "owner", "ts": 2000,
            "text": "Done",
        })

    def test_ts_as_float(self):
        assert is_valid_event({
            "type": "approve", "author": "reviewer", "ts": 1000.5,
        })


# --- parse_event ---

class TestParseEvent:
    def test_parse_comment(self):
        ev = parse_event({
            "type": "comment", "author": "reviewer", "ts": 1000,
            "threadId": "t1", "line": 10, "text": "hello",
        })
        assert ev.type == "comment"
        assert ev.author == "reviewer"
        assert ev.ts == 1000
        assert ev.thread_id == "t1"
        assert ev.line == 10
        assert ev.text == "hello"

    def test_parse_reply(self):
        ev = parse_event({
            "type": "reply", "author": "owner", "ts": 2000,
            "threadId": "t1", "text": "fixed",
        })
        assert ev.type == "reply"
        assert ev.author == "owner"
        assert ev.text == "fixed"
        assert ev.line is None

    def test_parse_approve(self):
        ev = parse_event({
            "type": "approve", "author": "reviewer", "ts": 3000,
        })
        assert ev.type == "approve"
        assert ev.thread_id is None
        assert ev.line is None
        assert ev.text is None

    def test_parse_round(self):
        ev = parse_event({
            "type": "round", "author": "reviewer", "ts": 4000, "round": 2,
        })
        assert ev.round == 2

    def test_float_ts_cast_to_int(self):
        ev = parse_event({
            "type": "approve", "author": "reviewer", "ts": 1000.7,
        })
        assert ev.ts == 1000


# --- append_event + read_events ---

class TestAppendAndRead:
    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        ev = LiveEvent(type="comment", author="reviewer", ts=1000,
                       thread_id="t1", line=5, text="Fix typo")
        append_event(path, ev)

        events, offset = read_events(path)
        assert len(events) == 1
        assert events[0].type == "comment"
        assert events[0].thread_id == "t1"
        assert events[0].line == 5
        assert events[0].text == "Fix typo"
        assert offset > 0

    def test_multiple_events(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        append_event(path, LiveEvent(type="comment", author="reviewer", ts=1000,
                                     thread_id="t1", line=1, text="A"))
        append_event(path, LiveEvent(type="reply", author="owner", ts=2000,
                                     thread_id="t1", text="B"))
        append_event(path, LiveEvent(type="resolve", author="reviewer", ts=3000,
                                     thread_id="t1"))

        events, _ = read_events(path)
        assert len(events) == 3
        assert [e.type for e in events] == ["comment", "reply", "resolve"]

    def test_read_with_offset(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        append_event(path, LiveEvent(type="comment", author="reviewer", ts=1000,
                                     thread_id="t1", line=1, text="A"))
        _, offset = read_events(path)

        append_event(path, LiveEvent(type="reply", author="owner", ts=2000,
                                     thread_id="t1", text="B"))

        events, _ = read_events(path, offset)
        assert len(events) == 1
        assert events[0].type == "reply"

    def test_read_nonexistent_file(self):
        events, offset = read_events("/nonexistent/path.jsonl")
        assert events == []
        assert offset == 0

    def test_offset_beyond_file_size(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        append_event(path, LiveEvent(type="approve", author="reviewer", ts=1000))
        events, _ = read_events(path, 999999)
        assert events == []

    def test_skips_invalid_json_lines(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        with open(path, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "approve", "author": "reviewer", "ts": 1000}) + "\n")
            f.write("{broken\n")
        events, _ = read_events(path)
        assert len(events) == 1
        assert events[0].type == "approve"

    def test_skips_invalid_event_schema(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "comment", "author": "reviewer", "ts": 1000}) + "\n")  # missing threadId
            f.write(json.dumps({"type": "approve", "author": "reviewer", "ts": 2000}) + "\n")
        events, _ = read_events(path)
        assert len(events) == 1
        assert events[0].type == "approve"

    def test_omits_none_fields(self, tmp_path):
        path = str(tmp_path / "test.review.jsonl")
        append_event(path, LiveEvent(type="approve", author="reviewer", ts=1000))
        with open(path) as f:
            obj = json.loads(f.readline())
        assert "threadId" not in obj
        assert "line" not in obj
        assert "text" not in obj
        assert "round" not in obj


# --- replay_events_to_threads ---

class TestReplayEventsToThreads:
    def test_single_comment_creates_thread(self):
        events = [LiveEvent(type="comment", author="reviewer", ts=1000,
                            thread_id="t1", line=5, text="Fix this")]
        threads = replay_events_to_threads(events)
        assert len(threads) == 1
        assert threads[0].id == "t1"
        assert threads[0].line == 5
        assert threads[0].status == "open"
        assert len(threads[0].messages) == 1
        assert threads[0].messages[0].text == "Fix this"

    def test_reply_adds_message(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix this"),
            LiveEvent(type="reply", author="owner", ts=2000,
                      thread_id="t1", text="Done"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads[0].messages) == 2
        assert threads[0].messages[1].author == "owner"
        assert threads[0].status == "pending"

    def test_reviewer_reply_sets_open(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix this"),
            LiveEvent(type="reply", author="owner", ts=2000,
                      thread_id="t1", text="Done"),
            LiveEvent(type="reply", author="reviewer", ts=3000,
                      thread_id="t1", text="Not quite"),
        ]
        threads = replay_events_to_threads(events)
        assert threads[0].status == "open"

    def test_resolve_and_unresolve(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix"),
            LiveEvent(type="resolve", author="reviewer", ts=2000,
                      thread_id="t1"),
        ]
        threads = replay_events_to_threads(events)
        assert threads[0].status == "resolved"

        events.append(LiveEvent(type="unresolve", author="reviewer", ts=3000,
                                thread_id="t1"))
        threads = replay_events_to_threads(events)
        assert threads[0].status == "open"

    def test_delete_removes_thread(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="Fix"),
            LiveEvent(type="delete", author="reviewer", ts=2000,
                      thread_id="t1"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 0

    def test_multiple_threads_preserve_order(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id="t1", line=5, text="A"),
            LiveEvent(type="comment", author="reviewer", ts=2000,
                      thread_id="t2", line=10, text="B"),
            LiveEvent(type="comment", author="reviewer", ts=3000,
                      thread_id="t3", line=15, text="C"),
        ]
        threads = replay_events_to_threads(events)
        assert [t.id for t in threads] == ["t1", "t2", "t3"]

    def test_reply_to_nonexistent_thread_ignored(self):
        events = [
            LiveEvent(type="reply", author="owner", ts=2000,
                      thread_id="nonexistent", text="Hello"),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 0

    def test_comment_missing_fields_skipped(self):
        events = [
            LiveEvent(type="comment", author="reviewer", ts=1000,
                      thread_id=None, line=5, text="No ID"),
            LiveEvent(type="comment", author="reviewer", ts=2000,
                      thread_id="t1", line=None, text="No line"),
            LiveEvent(type="comment", author="reviewer", ts=3000,
                      thread_id="t2", line=5, text=None),
        ]
        threads = replay_events_to_threads(events)
        assert len(threads) == 0
