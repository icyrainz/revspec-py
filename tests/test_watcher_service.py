"""Tests for watcher_service.py — LiveWatcherService and is_watcher_running."""

import json
import os
import tempfile

from revspec.watcher_service import LiveWatcherService, is_watcher_running


class TestLiveWatcherService:
    def test_poll_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            svc = LiveWatcherService(path)
            result = svc.poll()
            assert not result.has_new
            assert result.events == []
        finally:
            os.unlink(path)

    def test_poll_returns_owner_events(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "reply", "author": "owner", "ts": 1000, "threadId": "t1", "text": "hello"}) + "\n")
            f.write(json.dumps({"type": "comment", "author": "reviewer", "ts": 1001, "threadId": "t2", "line": 5, "text": "note"}) + "\n")
            path = f.name
        try:
            svc = LiveWatcherService(path)
            result = svc.poll()
            assert result.has_new
            assert len(result.events) == 1
            assert result.events[0].author == "owner"
        finally:
            os.unlink(path)

    def test_poll_advances_offset(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "reply", "author": "owner", "ts": 1000, "threadId": "t1", "text": "first"}) + "\n")
            path = f.name
        try:
            svc = LiveWatcherService(path)
            r1 = svc.poll()
            assert r1.has_new

            # Second poll with no new data
            r2 = svc.poll()
            assert not r2.has_new

            # Append more data
            with open(path, "a") as f:
                f.write(json.dumps({"type": "reply", "author": "owner", "ts": 2000, "threadId": "t1", "text": "second"}) + "\n")

            r3 = svc.poll()
            assert r3.has_new
            assert r3.events[0].text == "second"
        finally:
            os.unlink(path)

    def test_init_offset_skips_existing(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "reply", "author": "owner", "ts": 1000, "threadId": "t1", "text": "old"}) + "\n")
            path = f.name
        try:
            svc = LiveWatcherService(path)
            svc.init_offset()
            result = svc.poll()
            assert not result.has_new
        finally:
            os.unlink(path)

    def test_poll_missing_file(self):
        svc = LiveWatcherService("/tmp/nonexistent_revspec_test.jsonl")
        result = svc.poll()
        assert not result.has_new

    def test_reset_offset(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "reply", "author": "owner", "ts": 1000, "threadId": "t1", "text": "data"}) + "\n")
            path = f.name
        try:
            svc = LiveWatcherService(path)
            svc.init_offset()
            svc.reset_offset()
            result = svc.poll()
            assert result.has_new
        finally:
            os.unlink(path)


class TestIsWatcherRunning:
    def test_no_lock_file(self):
        assert not is_watcher_running("/tmp/nonexistent_revspec_spec.md")

    def test_lock_with_current_pid(self):
        with tempfile.TemporaryDirectory() as d:
            spec = os.path.join(d, "test.md")
            lock = os.path.join(d, "test.review.lock")
            with open(spec, "w") as f:
                f.write("# Test")
            with open(lock, "w") as f:
                f.write(str(os.getpid()))  # current process exists
            assert is_watcher_running(spec)

    def test_lock_with_dead_pid(self):
        with tempfile.TemporaryDirectory() as d:
            spec = os.path.join(d, "test.md")
            lock = os.path.join(d, "test.review.lock")
            with open(spec, "w") as f:
                f.write("# Test")
            with open(lock, "w") as f:
                f.write("999999999")  # very unlikely to be running
            assert not is_watcher_running(spec)

    def test_lock_with_invalid_content(self):
        with tempfile.TemporaryDirectory() as d:
            spec = os.path.join(d, "test.md")
            lock = os.path.join(d, "test.review.lock")
            with open(spec, "w") as f:
                f.write("# Test")
            with open(lock, "w") as f:
                f.write("not_a_pid")
            assert not is_watcher_running(spec)
