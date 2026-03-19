"""Integration tests for revspec watch CLI subcommand."""
import json
import pytest
from revspec.watch import run_watch


def _write_spec(tmp_path, content="# Spec\n\nSome content\n"):
    spec = tmp_path / "spec.md"
    spec.write_text(content)
    return spec


def _write_jsonl(tmp_path, events):
    jsonl = tmp_path / "spec.review.jsonl"
    with open(jsonl, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return jsonl


class TestWatchNoBlock:
    """Tests using REVSPEC_WATCH_NO_BLOCK=1 to avoid blocking."""

    def test_approve_event(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "approved" in captured.out.lower()

        # Lock and offset cleaned up
        assert not (tmp_path / "spec.review.lock").exists()
        assert not (tmp_path / "spec.review.offset").exists()

    def test_session_end_event(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "session-end", "author": "reviewer", "ts": 1000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "session ended" in captured.out.lower()

    def test_submit_event_outputs_threads(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Fix this section"},
            {"type": "resolve", "author": "reviewer", "ts": 2000,
             "threadId": "t1"},
            {"type": "submit", "author": "reviewer", "ts": 3000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "Rewrite Requested" in captured.out
        assert "Fix this section" in captured.out

    def test_new_comment_event(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Please fix"},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "New Comments" in captured.out
        assert "Please fix" in captured.out
        assert "revspec reply" in captured.out

    def test_no_events_no_output(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        # No JSONL file at all
        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_approve_takes_priority_over_submit(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "submit", "author": "reviewer", "ts": 1000},
            {"type": "approve", "author": "reviewer", "ts": 2000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "approved" in captured.out.lower()

    def test_owner_events_ignored(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "reply", "author": "owner", "ts": 1000,
             "threadId": "t1", "text": "Done"},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == ""


class TestWatchSpecNotFound:
    def test_exits_on_missing_spec(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            run_watch(str(tmp_path / "nonexistent.md"))
        assert exc_info.value.code == 1


class TestWatchLock:
    def test_creates_lock_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
        ])
        run_watch(str(spec))
        # Lock cleaned up after approve
        assert not (tmp_path / "spec.review.lock").exists()

    def test_stale_lock_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        lock = tmp_path / "spec.review.lock"
        lock.write_text("99999999")  # Non-existent PID
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
        ])
        run_watch(str(spec))  # Should not fail


class TestWatchApproveWithComments:
    """Tests for approve surfacing unprocessed comments."""

    def test_approve_with_comments_surfaces_threads(self, tmp_path, capsys, monkeypatch):
        """When approve arrives with unprocessed comments, output them."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "This needs work"},
            {"type": "approve", "author": "reviewer", "ts": 2000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "This needs work" in captured.out
        assert "approved" in captured.out.lower()
        # Reply instructions should be suppressed on approve
        assert "To reply:" not in captured.out
        assert "When done replying" not in captured.out

    def test_approve_without_comments_no_thread_output(self, tmp_path, capsys, monkeypatch):
        """When approve arrives alone, only output 'Review approved.'"""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == "Review approved.\n"

    def test_approve_with_reply_surfaces_thread(self, tmp_path, capsys, monkeypatch):
        """Replies in the same batch as approve should be surfaced."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Original comment"},
            {"type": "reply", "author": "reviewer", "ts": 2000,
             "threadId": "t1", "text": "Follow-up"},
            {"type": "approve", "author": "reviewer", "ts": 3000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "Original comment" in captured.out
        assert "Follow-up" in captured.out
        assert "approved" in captured.out.lower()


class TestWatchCrashRecovery:
    def test_recovery_reprocesses_submit(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Fix"},
            {"type": "resolve", "author": "reviewer", "ts": 2000,
             "threadId": "t1"},
            {"type": "submit", "author": "reviewer", "ts": 3000},
        ])
        # Set offset past all events (simulating prior read), but with wrong submit_ts
        jsonl = tmp_path / "spec.review.jsonl"
        offset_file = tmp_path / "spec.review.offset"
        offset_file.write_text(f"{jsonl.stat().st_size}\n0")

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "Rewrite Requested" in captured.out

    def test_recovery_reprocesses_approve(self, tmp_path, capsys, monkeypatch):
        """Crash recovery surfaces comments from a missed approve."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Needs improvement"},
            {"type": "approve", "author": "reviewer", "ts": 2000},
        ])
        # Offset at EOF — simulates agent that read events but crashed before output
        jsonl = tmp_path / "spec.review.jsonl"
        offset_file = tmp_path / "spec.review.offset"
        offset_file.write_text(str(jsonl.stat().st_size))

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "Needs improvement" in captured.out
        assert "approved" in captured.out.lower()

    def test_recovery_approve_only_surfaces_current_round(self, tmp_path, capsys, monkeypatch):
        """Crash recovery should not surface comments from prior rounds."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            # Round 1 — already processed
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Old comment"},
            {"type": "submit", "author": "reviewer", "ts": 2000},
            # Round 2 — the current round
            {"type": "comment", "author": "reviewer", "ts": 3000,
             "threadId": "t2", "line": 3, "text": "New comment"},
            {"type": "approve", "author": "reviewer", "ts": 4000},
        ])
        jsonl = tmp_path / "spec.review.jsonl"
        offset_file = tmp_path / "spec.review.offset"
        offset_file.write_text(str(jsonl.stat().st_size))

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "New comment" in captured.out
        assert "Old comment" not in captured.out
        assert "approved" in captured.out.lower()


class TestWatchSessionStart:
    """Tests for session-start event handling across sessions."""

    def test_old_approve_skipped_after_session_start(self, tmp_path, capsys, monkeypatch):
        """Fresh start: approve + session-start = old session, watcher waits."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Old comment"},
            {"type": "approve", "author": "reviewer", "ts": 2000},
            {"type": "session-start", "author": "reviewer", "ts": 5000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == ""  # no output — old approve is skipped

    def test_offline_approve_processed_without_session_start(self, tmp_path, capsys, monkeypatch):
        """Offline approve: no session-start after approve = current session, process it."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "approved" in captured.out.lower()

    def test_dedup_multiple_session_starts(self, tmp_path, capsys, monkeypatch):
        """Multiple session-starts after approve still skip the old approve."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
            {"type": "session-start", "author": "reviewer", "ts": 2000},
            {"type": "session-start", "author": "reviewer", "ts": 3000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == ""  # old approve is still skipped

    def test_new_approve_after_session_start_is_processed(self, tmp_path, capsys, monkeypatch):
        """New session's approve should be processed normally."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            # Session 1
            {"type": "approve", "author": "reviewer", "ts": 1000},
            # Session 2
            {"type": "session-start", "author": "reviewer", "ts": 2000},
            {"type": "comment", "author": "reviewer", "ts": 3000,
             "threadId": "t1", "line": 2, "text": "New feedback"},
            {"type": "approve", "author": "reviewer", "ts": 4000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert "New feedback" in captured.out
        assert "approved" in captured.out.lower()

    def test_crash_recovery_skips_approve_before_session_start(self, tmp_path, capsys, monkeypatch):
        """Crash recovery should not recover approve from a previous session."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "approve", "author": "reviewer", "ts": 1000},
            {"type": "session-start", "author": "reviewer", "ts": 2000},
        ])
        # Offset file exists at EOF — simulating a watcher that started and read to end
        jsonl = tmp_path / "spec.review.jsonl"
        offset_file = tmp_path / "spec.review.offset"
        offset_file.write_text(str(jsonl.stat().st_size))

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == ""  # no recovery — approve is from old session

    def test_interleaved_session_starts_trims_to_last(self, tmp_path, capsys, monkeypatch):
        """Trim uses last session-start, not first — old comments between are discarded."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "session-start", "author": "reviewer", "ts": 1000},
            {"type": "comment", "author": "reviewer", "ts": 2000,
             "threadId": "t1", "line": 2, "text": "Stale comment"},
            {"type": "session-start", "author": "reviewer", "ts": 3000},
            {"type": "approve", "author": "reviewer", "ts": 4000},
        ])

        run_watch(str(spec))
        captured = capsys.readouterr()
        # Only the approve after the last session-start should be processed
        assert "approved" in captured.out.lower()
        # Stale comment from before the last session-start should not appear
        assert "Stale comment" not in captured.out

    def test_crash_recovery_skips_submit_before_session_start(self, tmp_path, capsys, monkeypatch):
        """Crash recovery should not recover submit from a previous session."""
        monkeypatch.setenv("REVSPEC_WATCH_NO_BLOCK", "1")
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Old"},
            {"type": "resolve", "author": "reviewer", "ts": 2000,
             "threadId": "t1"},
            {"type": "submit", "author": "reviewer", "ts": 3000},
            {"type": "session-start", "author": "reviewer", "ts": 4000},
        ])
        jsonl = tmp_path / "spec.review.jsonl"
        offset_file = tmp_path / "spec.review.offset"
        offset_file.write_text(str(jsonl.stat().st_size))

        run_watch(str(spec))
        captured = capsys.readouterr()
        assert captured.out == ""  # no recovery — submit is from old session
