"""Tests for DiffState — pure diff computation logic."""
from revspec.diff_state import DiffState
from revspec.pager import _table_has_diff
from revspec.markdown import TableBlock


class TestNoDiff:
    def test_identical_lines(self):
        ds = DiffState(["a", "b", "c"], ["a", "b", "c"])
        assert ds.has_diff() is False
        assert ds.stats == (0, 0)
        assert ds.is_active is True

    def test_empty_lists(self):
        ds = DiffState([], [])
        assert ds.has_diff() is False


class TestAddedLines:
    def test_single_insert(self):
        ds = DiffState(["a", "c"], ["a", "b", "c"])
        assert ds.has_diff() is True
        assert ds.is_added(1) is True
        assert ds.is_added(0) is False
        assert ds.is_added(2) is False
        assert ds.stats == (1, 0)

    def test_append_at_end(self):
        ds = DiffState(["a"], ["a", "b", "c"])
        assert ds.is_added(1) is True
        assert ds.is_added(2) is True
        assert ds.stats == (2, 0)


class TestRemovedLines:
    def test_single_delete(self):
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        assert ds.has_diff() is True
        assert ds.removed_lines_before(1) == ["b"]
        assert ds.stats == (0, 1)

    def test_delete_at_end(self):
        ds = DiffState(["a", "b", "c"], ["a"])
        removed = ds.removed_lines_before(1)
        assert removed == ["b", "c"]

    def test_delete_at_start(self):
        ds = DiffState(["x", "a", "b"], ["a", "b"])
        assert ds.removed_lines_before(0) == ["x"]


class TestReplacedLines:
    def test_single_replace(self):
        ds = DiffState(["a", "old", "c"], ["a", "new", "c"])
        assert ds.is_added(1) is True
        assert ds.removed_lines_before(1) == ["old"]
        assert ds.stats == (1, 1)

    def test_multi_line_replace(self):
        ds = DiffState(["a", "x", "y", "c"], ["a", "p", "q", "r", "c"])
        assert ds.is_added(1) is True
        assert ds.is_added(2) is True
        assert ds.is_added(3) is True
        assert ds.removed_lines_before(1) == ["x", "y"]
        assert ds.stats == (3, 2)


class TestToggle:
    def test_toggle_off_and_on(self):
        ds = DiffState(["a"], ["a", "b"])
        assert ds.is_active is True
        result = ds.toggle()
        assert result is False
        assert ds.is_active is False
        result = ds.toggle()
        assert result is True
        assert ds.is_active is True


class TestHunkNavigation:
    def test_next_hunk(self):
        ds = DiffState(["a", "c"], ["a", "b", "c", "d"])
        target = ds.next_hunk(1)
        assert target == 2

    def test_next_hunk_skips_current(self):
        ds = DiffState(["a", "c"], ["a", "b", "c", "d"])
        target = ds.next_hunk(2)
        assert target == 4

    def test_prev_hunk(self):
        ds = DiffState(["a", "c"], ["a", "b", "c", "d"])
        target = ds.prev_hunk(4)
        assert target == 2

    def test_next_hunk_returns_none_at_end(self):
        ds = DiffState(["a"], ["a", "b"])
        target = ds.next_hunk(2)
        assert target is None

    def test_prev_hunk_returns_none_at_start(self):
        ds = DiffState(["a"], ["a", "b"])
        target = ds.prev_hunk(2)
        assert target is None

    def test_pure_delete_hunk(self):
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        target = ds.next_hunk(1)
        assert target == 2

    def test_trailing_delete_hunk(self):
        ds = DiffState(["a", "b", "c"], ["a", "b"])
        target = ds.next_hunk(1)
        assert target == 2


class TestAutojunkDisabled:
    def test_blank_lines_not_treated_as_junk(self):
        old = ["# Title", "", "content", "", "more"]
        new = ["# Title", "", "new content", "", "more"]
        ds = DiffState(old, new)
        assert ds.is_added(2) is True
        assert ds.removed_lines_before(2) == ["content"]
        assert ds.is_added(0) is False
        assert ds.is_added(1) is False
        assert ds.is_added(3) is False
        assert ds.is_added(4) is False


class TestGhostRowInterleaving:
    """Test DiffState contract for ghost row sequences."""

    def test_removed_line_produces_ghost_before_next(self):
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        assert ds.removed_lines_before(1) == ["b"]
        assert ds.removed_lines_before(0) == []

    def test_replace_produces_ghost_and_added(self):
        ds = DiffState(["a", "old", "c"], ["a", "new", "c"])
        assert ds.removed_lines_before(1) == ["old"]
        assert ds.is_added(1) is True

    def test_trailing_removal_uses_len_key(self):
        ds = DiffState(["a", "b", "c"], ["a"])
        assert ds.removed_lines_before(1) == ["b", "c"]

    def test_no_ghost_rows_when_inactive(self):
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        ds.toggle()
        assert ds.removed_lines_before(1) == ["b"]
        assert ds.is_active is False


class TestTableHasDiff:
    def _make_table_block(self, start, lines):
        """Create a minimal TableBlock for testing."""
        return TableBlock(start_index=start, lines=lines, col_widths=[], separator_index=-1)

    def test_no_diff_in_table(self):
        ds = DiffState(["a", "| x |", "| y |", "b"], ["a", "| x |", "| y |", "b"])
        block = self._make_table_block(1, ["| x |", "| y |"])
        assert _table_has_diff(block, ds) is False

    def test_added_line_in_table(self):
        ds = DiffState(["a", "| x |", "b"], ["a", "| x |", "| y |", "b"])
        block = self._make_table_block(1, ["| x |", "| y |"])
        assert _table_has_diff(block, ds) is True

    def test_removed_line_before_table(self):
        ds = DiffState(["a", "| z |", "| x |", "b"], ["a", "| x |", "b"])
        block = self._make_table_block(1, ["| x |"])
        assert _table_has_diff(block, ds) is True

    def test_table_unchanged_with_surrounding_diff(self):
        ds = DiffState(["a", "| x |", "b"], ["c", "| x |", "d"])
        block = self._make_table_block(1, ["| x |"])
        assert _table_has_diff(block, ds) is False
