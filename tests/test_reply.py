"""Integration tests for revspec reply CLI subcommand."""
import json
import pytest
from revspec_tui.reply import run_reply
from revspec_tui.protocol import read_events


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


class TestReply:
    def test_appends_reply_event(self, tmp_path):
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Fix this"},
        ])

        run_reply(str(spec), "t1", "Done, fixed it")

        events, _ = read_events(str(tmp_path / "spec.review.jsonl"))
        assert len(events) == 2
        reply = events[1]
        assert reply.type == "reply"
        assert reply.thread_id == "t1"
        assert reply.author == "owner"
        assert reply.text == "Done, fixed it"

    def test_cleans_shell_escaping(self, tmp_path):
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Fix"},
        ])

        run_reply(str(spec), "t1", "Done\\!")

        events, _ = read_events(str(tmp_path / "spec.review.jsonl"))
        assert events[1].text == "Done!"

    def test_missing_spec_file_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            run_reply(str(tmp_path / "nonexistent.md"), "t1", "hello")
        assert exc_info.value.code == 1

    def test_empty_text_exits(self, tmp_path):
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Fix"},
        ])

        with pytest.raises(SystemExit) as exc_info:
            run_reply(str(spec), "t1", "  ")
        assert exc_info.value.code == 1

    def test_nonexistent_thread_exits(self, tmp_path):
        spec = _write_spec(tmp_path)
        _write_jsonl(tmp_path, [
            {"type": "comment", "author": "reviewer", "ts": 1000,
             "threadId": "t1", "line": 2, "text": "Fix"},
        ])

        with pytest.raises(SystemExit) as exc_info:
            run_reply(str(spec), "nonexistent", "hello")
        assert exc_info.value.code == 1

    def test_missing_jsonl_exits(self, tmp_path):
        spec = _write_spec(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            run_reply(str(spec), "t1", "hello")
        assert exc_info.value.code == 1
