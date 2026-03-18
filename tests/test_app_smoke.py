"""Smoke tests for RevspecApp — exercises wiring between extracted modules.

Uses Textual's async test harness (app.run_test) to verify that the app
launches, handles key presses, and delegates correctly to extracted modules.
"""

import os
import json
import tempfile
import shutil

import pytest

from revspec.app import RevspecApp


@pytest.fixture
def spec_dir(tmp_path):
    """Create a temp directory with a test spec file."""
    spec = tmp_path / "test.md"
    spec.write_text(
        "# Title\n\nSome text on line 3.\n\n## Section\n\nMore text on line 7.\n\n"
        "Another line.\n\n### Subsection\n\nDeep text.\n"
    )
    return tmp_path, str(spec)


@pytest.fixture
def spec_with_jsonl(spec_dir):
    """Create spec + a pre-existing JSONL with one thread."""
    tmp_path, spec_path = spec_dir
    jsonl_path = tmp_path / "test.review.jsonl"
    jsonl_path.write_text(
        json.dumps({"type": "comment", "author": "reviewer", "ts": 1000,
                     "threadId": "abc12345", "line": 3, "text": "Looks good"}) + "\n"
    )
    return tmp_path, spec_path


class TestAppLaunch:
    @pytest.mark.asyncio
    async def test_app_starts_and_exits(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # App should be running with state initialized
            assert app.state.line_count > 0
            assert app.pager_widget is not None
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_cursor_navigation(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            assert app.state.cursor_line == 1
            await pilot.press("j")
            assert app.state.cursor_line == 2
            await pilot.press("k")
            assert app.state.cursor_line == 1
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_count_prefix_j(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            assert app.state.cursor_line == 1
            await pilot.press("5")
            await pilot.press("j")
            assert app.state.cursor_line == 6
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_count_prefix_G(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            await pilot.press("3")
            await pilot.press("G")
            assert app.state.cursor_line == 3
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_gg_goes_to_top(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # Move down first
            await pilot.press("G")
            assert app.state.cursor_line == app.state.line_count
            await pilot.press("g")
            await pilot.press("g")
            assert app.state.cursor_line == 1
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_jump_list_wiring(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            await pilot.press("G")  # jump to bottom
            bottom = app.state.cursor_line
            assert bottom > 1
            await pilot.press("ctrl+o")  # jump back
            assert app.state.cursor_line == 1
            await pilot.press("ctrl+c")


class TestAppWithThreads:
    @pytest.mark.asyncio
    async def test_loads_existing_threads(self, spec_with_jsonl):
        _, spec_path = spec_with_jsonl
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            assert len(app.state.threads) == 1
            assert app.state.threads[0].id == "abc12345"
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_thread_navigation(self, spec_with_jsonl):
        _, spec_path = spec_with_jsonl
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # Navigate to thread
            await pilot.press("right_square_bracket")
            await pilot.press("t")
            assert app.state.cursor_line == 3  # thread is on line 3
            await pilot.press("ctrl+c")


class TestAppReload:
    @pytest.mark.asyncio
    async def test_reload_resets_jump_list(self, spec_dir):
        """Verify _do_reload properly resets JumpList (the critical bug fix)."""
        tmp_path, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # Navigate to create jump history
            await pilot.press("G")
            assert app.state.cursor_line > 1

            # Simulate reload
            new_content = "# New Title\n\nNew content.\n"
            app._do_reload(new_content, app._spec_mtime + 1)

            # JumpList should be fresh — push and backward should work
            app._jump_list.push(2)
            target = app._jump_list.backward(2, app.state.line_count)
            assert target == 1  # initial entry
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_reload_resets_watcher_offset(self, spec_with_jsonl):
        """Verify _do_reload resets watcher service offset."""
        _, spec_path = spec_with_jsonl
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # After mount, offset should be at end of JSONL (skipping existing)
            app._watcher_service.init_offset()
            r1 = app._watcher_service.poll()
            assert not r1.has_new  # nothing new since init

            # Simulate reload — should reset offset to current file size
            new_content = "# New Title\n\nNew content.\n"
            app._do_reload(new_content, app._spec_mtime + 1)

            # Poll after reload should return empty (offset at end)
            r2 = app._watcher_service.poll()
            assert not r2.has_new
            await pilot.press("ctrl+c")


class TestCommandModeWiring:
    @pytest.mark.asyncio
    async def test_goto_line_via_command(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # Directly test _process_command wiring
            app._process_command("5")
            assert app.state.cursor_line == 5
            await pilot.press("ctrl+c")

    @pytest.mark.asyncio
    async def test_unknown_command(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            # Should not crash on unknown command
            app._process_command("foobar")
            await pilot.press("ctrl+c")


class TestSequenceRouterWiring:
    @pytest.mark.asyncio
    async def test_router_initialized(self, spec_dir):
        _, spec_path = spec_dir
        app = RevspecApp(spec_path)
        async with app.run_test() as pilot:
            assert app._seq_router is not None
            assert app._seq_router.is_prefix("g")
            assert app._seq_router.is_prefix("right_square_bracket")
            await pilot.press("ctrl+c")
