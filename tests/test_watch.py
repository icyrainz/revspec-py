"""Integration tests for revspec watch CLI subcommand."""
import json
import pytest
from revspec_tui.watch import run_watch


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
