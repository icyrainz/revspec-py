"""Tests for navigation.py — JumpList and heading_breadcrumb."""

from revspec.navigation import JumpList, HeadingIndex, heading_breadcrumb


# --- JumpList ---

class TestJumpListPush:
    def test_initial_state(self):
        jl = JumpList()
        # Should not go backward from initial
        assert jl.backward(1, 100) is None

    def test_push_records_position(self):
        jl = JumpList()
        jl.push(10)
        jl.push(20)
        assert jl.backward(20, 100) == 10

    def test_push_deduplicates_tail(self):
        jl = JumpList()
        jl.push(10)
        jl.push(10)  # duplicate — only one 10 entry kept
        target = jl.backward(10, 100)
        assert target == 1  # initial (10 deduplicated)

    def test_push_truncates_forward_history(self):
        jl = JumpList()
        jl.push(10)
        jl.push(20)
        jl.push(30)
        jl.backward(30, 100)  # at 20
        jl.backward(20, 100)  # at 10
        jl.push(50)  # should truncate 20, 30
        assert jl.forward(100) is None  # forward history gone

    def test_max_size_eviction(self):
        jl = JumpList(max_size=5)
        for i in range(1, 10):
            jl.push(i * 10)
        # Should have at most 5 entries
        count = 0
        pos = 90
        while True:
            target = jl.backward(pos, 100)
            if target is None:
                break
            pos = target
            count += 1
        assert count <= 5


class TestJumpListBackward:
    def test_backward_from_end(self):
        jl = JumpList()
        jl.push(10)
        jl.push(20)
        assert jl.backward(20, 100) == 10

    def test_backward_records_current_if_different(self):
        jl = JumpList()
        jl.push(10)
        # Current position (50) differs from last entry (10)
        target = jl.backward(50, 100)
        assert target == 10

    def test_backward_clamps_to_line_count(self):
        jl = JumpList()
        jl.push(999)
        assert jl.backward(999, 50) == 1  # initial entry clamped

    def test_backward_empty_returns_none(self):
        jl = JumpList()
        assert jl.backward(1, 100) is None


class TestJumpListForward:
    def test_forward_after_backward(self):
        jl = JumpList()
        jl.push(10)
        jl.push(20)
        jl.backward(20, 100)  # now at 10
        assert jl.forward(100) == 20

    def test_forward_at_end_returns_none(self):
        jl = JumpList()
        jl.push(10)
        assert jl.forward(100) is None

    def test_forward_clamps_to_line_count(self):
        jl = JumpList()
        jl.push(10)
        jl.push(999)
        jl.backward(999, 50)  # at 10
        assert jl.forward(50) == 50  # 999 clamped to 50


class TestJumpListSwap:
    def test_swap_basic(self):
        jl = JumpList()
        jl.push(10)
        jl.push(20)
        target = jl.swap(20, 100)
        assert target == 10

    def test_swap_returns_none_if_less_than_2(self):
        jl = JumpList()
        assert jl.swap(1, 100) is None

    def test_swap_roundtrip(self):
        jl = JumpList()
        jl.push(10)
        jl.push(20)
        t1 = jl.swap(20, 100)  # index moves to prev, returns 10
        assert t1 == 10
        t2 = jl.swap(t1, 100)  # swap again
        assert t2 is not None  # swaps to some previous entry

    def test_swap_clamps(self):
        jl = JumpList()
        jl.push(10)
        jl.push(999)
        target = jl.swap(999, 50)
        assert target is not None
        assert target <= 50


# --- heading_breadcrumb ---

class TestHeadingBreadcrumb:
    def test_finds_h1(self):
        lines = ["# Title", "some text", "more text"]
        assert heading_breadcrumb(lines, 3) == "Title"

    def test_finds_h2(self):
        lines = ["# Title", "## Section", "text"]
        assert heading_breadcrumb(lines, 3) == "Section"

    def test_finds_h3(self):
        lines = ["# Title", "## Section", "### Sub", "text"]
        assert heading_breadcrumb(lines, 4) == "Sub"

    def test_finds_nearest_above(self):
        lines = ["# First", "text", "## Second", "text", "## Third", "text"]
        assert heading_breadcrumb(lines, 6) == "Third"

    def test_no_heading_returns_none(self):
        lines = ["text", "more text", "even more"]
        assert heading_breadcrumb(lines, 3) is None

    def test_cursor_on_heading_line(self):
        lines = ["# Title", "## Section"]
        # cursor_line=2 (1-based), so we search from index 1 downward
        assert heading_breadcrumb(lines, 2) == "Section"

    def test_cursor_line_1_with_heading(self):
        lines = ["# Title", "text"]
        assert heading_breadcrumb(lines, 1) == "Title"

    def test_cursor_line_1_no_heading(self):
        lines = ["text", "# Title"]
        assert heading_breadcrumb(lines, 1) is None

    def test_strips_whitespace(self):
        lines = ["#  Title  with  spaces  ", "text"]
        assert heading_breadcrumb(lines, 2) == "Title  with  spaces"


# --- HeadingIndex ---

class TestHeadingIndex:
    def test_breadcrumb(self):
        lines = ["# Title", "text", "## Section", "text"]
        idx = HeadingIndex(lines)
        assert idx.breadcrumb(2) == "Title"
        assert idx.breadcrumb(4) == "Section"

    def test_breadcrumb_none(self):
        idx = HeadingIndex(["text", "more text"])
        assert idx.breadcrumb(1) is None

    def test_next_heading(self):
        lines = ["# H1", "text", "## H2", "text", "## H2b"]
        idx = HeadingIndex(lines)
        assert idx.next_heading(2, 1) == 3  # first ## after line 1
        assert idx.next_heading(2, 3) == 5  # second ## after line 3

    def test_next_heading_wraps(self):
        lines = ["## First", "text", "## Second"]
        idx = HeadingIndex(lines)
        assert idx.next_heading(2, 3) == 1  # wraps to first

    def test_prev_heading(self):
        lines = ["# H1", "text", "## H2", "text", "## H2b"]
        idx = HeadingIndex(lines)
        assert idx.prev_heading(2, 5) == 3

    def test_prev_heading_wraps(self):
        lines = ["## First", "text", "## Second"]
        idx = HeadingIndex(lines)
        assert idx.prev_heading(2, 1) == 3  # wraps to last

    def test_no_heading_returns_none(self):
        idx = HeadingIndex(["text", "more text"])
        assert idx.next_heading(1, 1) is None
        assert idx.prev_heading(1, 1) is None

    def test_rebuild(self):
        idx = HeadingIndex(["text"])
        assert idx.breadcrumb(1) is None
        idx.rebuild(["# New Title", "text"])
        assert idx.breadcrumb(2) == "New Title"
