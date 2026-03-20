# Round Diff View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show inline unified diff annotations in the pager after each spec reload, so reviewers can instantly see what changed between rounds.

**Architecture:** New `DiffState` class (pure logic, no Textual) computes line-level diffs using `difflib.SequenceMatcher`. The app creates `DiffState` on reload, passes it to the pager, which interleaves ghost rows (removed lines) into the visual model and applies green/red background tinting to added/removed lines. Toggle via `\d`, navigate hunks via `]d`/`[d`.

**Tech Stack:** Python stdlib `difflib`, `bisect`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-18-round-diff-view-design.md`

---

### Task 1: DiffState class — core diff computation

**Files:**
- Create: `revspec/diff_state.py`
- Create: `tests/test_diff_state.py`

- [ ] **Step 1: Write failing tests for DiffState construction and basic queries**

```python
# tests/test_diff_state.py
"""Tests for DiffState — pure diff computation logic."""
from revspec.diff_state import DiffState


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
        assert ds.is_added(1) is True  # "b" at index 1
        assert ds.is_added(0) is False  # "a" unchanged
        assert ds.is_added(2) is False  # "c" unchanged
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
        assert ds.removed_lines_before(1) == ["b"]  # "b" removed before new index 1 ("c")
        assert ds.stats == (0, 1)

    def test_delete_at_end(self):
        ds = DiffState(["a", "b", "c"], ["a"])
        removed = ds.removed_lines_before(1)  # key = len(new_lines)
        assert removed == ["b", "c"]

    def test_delete_at_start(self):
        ds = DiffState(["x", "a", "b"], ["a", "b"])
        assert ds.removed_lines_before(0) == ["x"]


class TestReplacedLines:
    def test_single_replace(self):
        ds = DiffState(["a", "old", "c"], ["a", "new", "c"])
        assert ds.is_added(1) is True  # "new" is added
        assert ds.removed_lines_before(1) == ["old"]  # "old" removed before index 1
        assert ds.stats == (1, 1)

    def test_multi_line_replace(self):
        ds = DiffState(["a", "x", "y", "c"], ["a", "p", "q", "r", "c"])
        assert ds.is_added(1) is True  # "p"
        assert ds.is_added(2) is True  # "q"
        assert ds.is_added(3) is True  # "r"
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
        # Lines: a(eq), b(added), c(eq), d(added)
        ds = DiffState(["a", "c"], ["a", "b", "c", "d"])
        # From line 1 (spec line 1 = index 0), next hunk is at index 1 → spec line 2
        target = ds.next_hunk(1)
        assert target == 2  # "b" at index 1 → spec line 2

    def test_next_hunk_skips_current(self):
        ds = DiffState(["a", "c"], ["a", "b", "c", "d"])
        # From line 2 (on the first hunk), next hunk is at index 3 → spec line 4
        target = ds.next_hunk(2)
        assert target == 4

    def test_prev_hunk(self):
        ds = DiffState(["a", "c"], ["a", "b", "c", "d"])
        # From line 4 (on last hunk), prev is at index 1 → spec line 2
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
        # "b" deleted — hunk starts at index 1 (the line after deletion) → spec line 2
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        target = ds.next_hunk(1)
        assert target == 2  # spec line 2 ("c"), deletion above

    def test_trailing_delete_hunk(self):
        # "c" deleted at end — hunk at len(new_lines)=2 → spec line 2 (last line)
        ds = DiffState(["a", "b", "c"], ["a", "b"])
        target = ds.next_hunk(1)
        assert target == 2


class TestAutojunkDisabled:
    """Verify autojunk=False prevents blank-line junk heuristic."""
    def test_blank_lines_not_treated_as_junk(self):
        old = ["# Title", "", "content", "", "more"]
        new = ["# Title", "", "new content", "", "more"]
        ds = DiffState(old, new)
        assert ds.is_added(2) is True  # "new content" replaced "content"
        assert ds.removed_lines_before(2) == ["content"]
        assert ds.is_added(0) is False
        assert ds.is_added(1) is False  # blank line not shifted
        assert ds.is_added(3) is False
        assert ds.is_added(4) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_diff_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'revspec.diff_state'`

- [ ] **Step 3: Implement DiffState class**

```python
# revspec/diff_state.py
"""DiffState — line-level diff computation between two spec versions."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher


class DiffState:
    """Computes and exposes line-level diff between two spec versions.

    Uses difflib.SequenceMatcher with autojunk=False to prevent blank lines
    (common in markdown) from being treated as junk.
    """

    def __init__(self, old_lines: list[str], new_lines: list[str]) -> None:
        self._added: set[int] = set()
        self._removed_blocks: dict[int, list[str]] = {}
        self._hunk_starts: list[int] = []
        self._is_active: bool = True

        sm = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        added_count = 0
        removed_count = 0
        hunk_set: set[int] = set()

        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            elif op == "insert":
                for j in range(j1, j2):
                    self._added.add(j)
                added_count += j2 - j1
                hunk_set.add(j1)
            elif op == "delete":
                self._removed_blocks[j1] = old_lines[i1:i2]
                removed_count += i2 - i1
                hunk_set.add(j1)
            elif op == "replace":
                self._removed_blocks[j1] = old_lines[i1:i2]
                removed_count += i2 - i1
                for j in range(j1, j2):
                    self._added.add(j)
                added_count += j2 - j1
                hunk_set.add(j1)

        self._stats = (added_count, removed_count)
        self._hunk_starts = sorted(hunk_set)

    def is_added(self, new_idx: int) -> bool:
        """True if this new-file line was added or changed."""
        return new_idx in self._added

    def removed_lines_before(self, new_idx: int) -> list[str]:
        """Returns removed lines that should appear before new_idx."""
        return self._removed_blocks.get(new_idx, [])

    def has_diff(self) -> bool:
        """True if any lines differ between old and new."""
        return bool(self._added or self._removed_blocks)

    def toggle(self) -> bool:
        """Flip active state. Returns new state."""
        self._is_active = not self._is_active
        return self._is_active

    @property
    def is_active(self) -> bool:
        """Whether diff annotations are currently visible."""
        return self._is_active

    @property
    def stats(self) -> tuple[int, int]:
        """Returns (added_count, removed_count)."""
        return self._stats

    def next_hunk(self, current_spec_line: int) -> int | None:
        """Returns spec line (1-based) of next diff hunk after current_spec_line."""
        if not self._hunk_starts:
            return None
        # Convert 1-based spec line to 0-based index
        current_idx = current_spec_line - 1
        # Find first hunk start strictly after current_idx
        pos = bisect_right(self._hunk_starts, current_idx)
        if pos >= len(self._hunk_starts):
            return None
        hunk_idx = self._hunk_starts[pos]
        # For pure-delete hunks at end of file, clamp to last line
        # hunk_idx is 0-based new-file index → 1-based spec line
        return hunk_idx + 1

    def prev_hunk(self, current_spec_line: int) -> int | None:
        """Returns spec line (1-based) of previous diff hunk before current_spec_line."""
        if not self._hunk_starts:
            return None
        current_idx = current_spec_line - 1
        pos = bisect_left(self._hunk_starts, current_idx)
        if pos <= 0:
            return None
        hunk_idx = self._hunk_starts[pos - 1]
        return hunk_idx + 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_diff_state.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add revspec/diff_state.py tests/test_diff_state.py
git commit -m "feat: add DiffState class for line-level diff computation"
```

---

### Task 2: Theme colors for diff backgrounds

**Files:**
- Modify: `revspec/theme.py:9-28` (add 2 entries to THEME dict)

- [ ] **Step 1: Write failing test for new theme keys**

```python
# Append to tests/test_renderer.py (or inline check — theme keys are trivial)
# Actually, just verify after implementation. Theme is a dict — no logic to test.
```

Skip TDD for this — it's a two-line data addition with no logic.

- [ ] **Step 2: Add diff colors to THEME**

In `revspec/theme.py`, add after the `"info"` entry (line 27):

```python
    "diff_added_bg": "#1a3b1e",    # subtle dark green background
    "diff_removed_bg": "#3b1a1e",  # subtle dark red background
```

- [ ] **Step 3: Commit**

```bash
git add revspec/theme.py
git commit -m "feat: add diff background colors to theme"
```

---

### Task 3: Key dispatch registry — \d, ]d, [d

**Files:**
- Modify: `revspec/key_dispatch.py:19-43` (add 3 entries to SEQUENCE_REGISTRY)
- Modify: `tests/test_key_dispatch.py` (add tests for new sequences)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_key_dispatch.py`:

```python
class TestDiffSequences:
    def test_toggle_diff_resolves(self):
        router = SequenceRouter()
        assert router.resolve("backslash", "d") == "_toggle_diff"

    def test_next_hunk_resolves(self):
        router = SequenceRouter()
        assert router.resolve("right_square_bracket", "d") == "_next_hunk"

    def test_prev_hunk_resolves(self):
        router = SequenceRouter()
        assert router.resolve("left_square_bracket", "d") == "_prev_hunk"

    def test_backslash_hints_include_diff(self):
        router = SequenceRouter()
        hints = router.hints_for_prefix("backslash")
        displays = [h[0] for h in hints]
        assert "\\d" in displays

    def test_bracket_hints_include_diff(self):
        router = SequenceRouter()
        hints = router.hints_for_prefix("right_square_bracket")
        displays = [h[0] for h in hints]
        assert "]d" in displays
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_key_dispatch.py::TestDiffSequences -v`
Expected: FAIL — `resolve()` returns `None`

- [ ] **Step 3: Add registry entries**

In `revspec/key_dispatch.py`, add to `SEQUENCE_REGISTRY` (after the `\n` entry at line 42):

```python
    KeySequence("backslashd", "\\d", "diff", "_toggle_diff"),
```

And add to the `]` prefix section (after `]3` at line 25):

```python
    KeySequence("right_square_bracketd", "]d", "diff\u2192", "_next_hunk"),
```

And add to the `[` prefix section (after `[3` at line 31):

```python
    KeySequence("left_square_bracketd", "[d", "\u2190diff", "_prev_hunk"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_key_dispatch.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add revspec/key_dispatch.py tests/test_key_dispatch.py
git commit -m "feat: add \\d, ]d, [d to key sequence registry"
```

---

### Task 4: Command alias — :diff

**Files:**
- Modify: `revspec/commands.py:21-59` (add `"diff"` case)
- Modify: `tests/test_commands.py` (add test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_commands.py`:

```python
class TestDiffCommand:
    def test_diff(self):
        assert parse_command("diff").action == "diff"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_commands.py::TestDiffCommand -v`
Expected: FAIL — `action == "unknown"`

- [ ] **Step 3: Add diff command**

In `revspec/commands.py`, add after the `wrap` case (line 50):

```python
    if cmd == "diff":
        return CommandResult(action="diff")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_commands.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add revspec/commands.py tests/test_commands.py
git commit -m "feat: add :diff command alias"
```

---

### Task 5: Pager — ghost rows in visual model

**Files:**
- Modify: `revspec/pager.py:46-58` (add `diff_state` attribute)
- Modify: `revspec/pager.py:68-116` (rebuild_visual_model — interleave ghost rows)
- Modify: `revspec/pager.py:132-138` (spec_line_at_visual_row — ghost row resolution)

This task modifies `rebuild_visual_model()` to insert `("diff_removed", text)` and `("diff_removed_wrap", text, seg)` ghost rows, and updates `spec_line_at_visual_row` to handle them via `bisect_left`.

- [ ] **Step 1: Write failing tests for ghost row interleaving**

Create a helper that builds a pager-like visual model to test the logic in isolation. Since `rebuild_visual_model` depends on Textual's `ScrollView`, we test via the pager directly using a minimal setup.

Append to `tests/test_diff_state.py`:

```python
class TestGhostRowInterleaving:
    """Test that DiffState data produces correct ghost row sequences.

    These tests verify the contract between DiffState and the pager's
    rebuild_visual_model — ghost rows appear before the correct spec lines.
    """

    def test_removed_line_produces_ghost_before_next(self):
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        # "b" removed — ghost should appear before index 1 ("c")
        assert ds.removed_lines_before(1) == ["b"]
        assert ds.removed_lines_before(0) == []

    def test_replace_produces_ghost_and_added(self):
        ds = DiffState(["a", "old", "c"], ["a", "new", "c"])
        assert ds.removed_lines_before(1) == ["old"]
        assert ds.is_added(1) is True

    def test_trailing_removal_uses_len_key(self):
        ds = DiffState(["a", "b", "c"], ["a"])
        # Removals at end keyed by len(new_lines) = 1
        assert ds.removed_lines_before(1) == ["b", "c"]

    def test_no_ghost_rows_when_inactive(self):
        ds = DiffState(["a", "b", "c"], ["a", "c"])
        ds.toggle()  # deactivate
        # DiffState still returns data — pager checks is_active before using it
        assert ds.removed_lines_before(1) == ["b"]
        assert ds.is_active is False
```

- [ ] **Step 2: Run tests to verify they pass**

These tests use the already-implemented `DiffState` class — they should pass immediately. This validates the contract before modifying the pager.

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_diff_state.py::TestGhostRowInterleaving -v`
Expected: All PASS

- [ ] **Step 3: Add diff_state attribute to SpecPager.__init__**

In `revspec/pager.py`, add after line 55 (`self._rich_console = ...`):

```python
        self.diff_state: DiffState | None = None
```

And add the import at the top of the file (after the `from .state import ReviewState` line):

```python
from .diff_state import DiffState
```

- [ ] **Step 4: Add helper to check if a table block has diffs**

In `revspec/pager.py`, add as a module-level function before the `SpecPager` class:

```python
def _table_has_diff(block: TableBlock, diff_state: DiffState) -> bool:
    """Check if any line in a table block has diff changes."""
    for idx in range(block.start_index, block.start_index + len(block.lines)):
        if diff_state.is_added(idx) or diff_state.removed_lines_before(idx):
            return True
    return False
```

- [ ] **Step 5: Modify rebuild_visual_model to interleave ghost rows**

Replace the `rebuild_visual_model` method body in `revspec/pager.py` (lines 68–116). The new version adds ghost row insertion and table-with-diff handling:

```python
    def rebuild_visual_model(self) -> None:
        """Rebuild the visual row model from spec lines."""
        lines = self.state.spec_lines
        if self._table_blocks is None:
            self._table_blocks = scan_table_blocks(lines)

        self._update_gutter_cache()
        width = self.size.width if self.size.width > 0 else 200
        gutter_total = self._cached_gutter_total
        content_width = width - gutter_total if self.wrap_width > 0 else 0

        diff = self.diff_state
        diff_active = diff is not None and diff.is_active

        # Ghost row gutter width matches spec gutter for column alignment
        ghost_gutter_width = gutter_total
        ghost_content_width = width - ghost_gutter_width

        rows: list[tuple] = []
        in_code = False
        code_state_map: dict[int, bool] = {}
        spec_to_vis: dict[int, int] = {}
        spec_row_indices: list[int] = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Ghost rows BEFORE this spec line
            if diff_active:
                for removed_text in diff.removed_lines_before(i):
                    rows.append(("diff_removed", removed_text))
                    if content_width > 0 and ghost_content_width > 0 and len(removed_text) > ghost_content_width:
                        extra = (len(removed_text) - 1) // ghost_content_width
                        for seg in range(1, extra + 1):
                            rows.append(("diff_removed_wrap", removed_text, seg))

            table_block = self._table_blocks.get(i)
            # Skip table rendering if table has diffs — render as raw text
            is_table = (
                table_block is not None
                and not self.search_query
                and not (diff_active and _table_has_diff(table_block, diff))
            )

            code_state_map[i] = in_code

            if line.strip().startswith("```"):
                in_code = not in_code

            if is_table:
                rel_idx = i - table_block.start_index
                if rel_idx == 0:
                    rows.append(("table_border", i, "top"))
                spec_to_vis[i + 1] = len(rows)
                spec_row_indices.append(len(rows))
                rows.append(("spec", i))
                if rel_idx == len(table_block.lines) - 1:
                    rows.append(("table_border", i, "bottom"))
            else:
                spec_to_vis[i + 1] = len(rows)
                spec_row_indices.append(len(rows))
                rows.append(("spec", i))
                if content_width > 0 and len(line) > content_width:
                    extra = (len(line) - 1) // content_width
                    for seg in range(1, extra + 1):
                        rows.append(("spec_wrap", i, seg))

            i += 1

        # Trailing removed lines after the last spec line
        if diff_active:
            for removed_text in diff.removed_lines_before(len(lines)):
                rows.append(("diff_removed", removed_text))
                if content_width > 0 and ghost_content_width > 0 and len(removed_text) > ghost_content_width:
                    extra = (len(removed_text) - 1) // ghost_content_width
                    for seg in range(1, extra + 1):
                        rows.append(("diff_removed_wrap", removed_text, seg))

        self._visual_rows = rows
        self._code_state_map = code_state_map
        self._spec_to_visual = spec_to_vis
        self._spec_row_indices = spec_row_indices
        self.virtual_size = Size(width, len(rows))
```

- [ ] **Step 6: Update spec_line_at_visual_row for ghost rows**

Replace `spec_line_at_visual_row` in `revspec/pager.py` (lines 132–138):

```python
    def spec_line_at_visual_row(self, vis_row: int) -> int:
        """Map visual row to spec line (1-based). Resolves ghost rows forward."""
        if vis_row < 0:
            return 1
        if vis_row >= len(self._visual_rows):
            return self.state.line_count
        row = self._visual_rows[vis_row]
        kind = row[0]
        if kind in ("spec", "spec_wrap", "table_border"):
            return row[1] + 1
        # Ghost row — resolve to next spec line via bisect
        if not hasattr(self, "_spec_row_indices") or not self._spec_row_indices:
            return self.state.line_count
        pos = bisect_left(self._spec_row_indices, vis_row)
        if pos >= len(self._spec_row_indices):
            return self.state.line_count  # trailing ghost rows → last spec line
        spec_vis = self._spec_row_indices[pos]
        return self._visual_rows[spec_vis][1] + 1
```

Add the `bisect_left` import at the top of `pager.py`:

```python
from bisect import bisect_left
```

- [ ] **Step 7: Initialize _spec_row_indices in __init__**

In `SpecPager.__init__`, add after `self._spec_to_visual`:

```python
        self._spec_row_indices: list[int] = []
```

- [ ] **Step 8: Run all existing tests to verify no regressions**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest -x -q`
Expected: All existing tests PASS

- [ ] **Step 9: Commit**

```bash
git add revspec/pager.py
git commit -m "feat: add ghost rows to pager visual model for diff view"
```

---

### Task 6: Pager — render ghost rows and diff-added styling

**Files:**
- Modify: `revspec/pager.py:169-295` (render_line — add ghost row branch, diff-added bg)

- [ ] **Step 1: Add ghost row rendering to render_line**

In `revspec/pager.py`'s `render_line` method, add a new branch **after** the `table_border` branch (line 190) and **before** the `spec_wrap` branch (line 192):

```python
        # --- Ghost rows (diff removed) ---
        if row[0] == "diff_removed":
            removed_text = row[1]
            bg = THEME["diff_removed_bg"]
            text = Text()
            # Gutter: [space][space][-][padding] — same width as spec gutter
            text.append(" ", Style(bgcolor=bg))  # cursor column
            text.append(" ", Style(bgcolor=bg))  # gutter icon column
            text.append("-", Style(color=THEME["red"], bgcolor=bg))
            if self.show_line_numbers:
                text.append(" " * (num_width + 1), Style(bgcolor=bg))
            content = removed_text if removed_text else " "
            if self.wrap_width > 0:
                ghost_cw = width - gutter_total
                if ghost_cw > 0 and len(content) > ghost_cw:
                    content = content[:ghost_cw]
            text.append(content, Style(color=THEME["text_dim"], bgcolor=bg))
            # Pad with diff bg (not default crust) so the full row is tinted
            pad = width - text.cell_len
            if pad > 0:
                text.append(" " * pad, Style(bgcolor=bg))
            return Strip(list(text.render(self._rich_console))).crop(0, width)

        if row[0] == "diff_removed_wrap":
            removed_text = row[1]
            seg = row[2]
            bg = THEME["diff_removed_bg"]
            ghost_cw = width - gutter_total
            start = seg * ghost_cw
            end = start + ghost_cw
            segment_text = removed_text[start:end]
            text = Text()
            text.append(" " * gutter_total, Style(bgcolor=bg))
            text.append(segment_text, Style(color=THEME["text_dim"], bgcolor=bg))
            # Pad with diff bg
            pad = width - text.cell_len
            if pad > 0:
                text.append(" " * pad, Style(bgcolor=bg))
            return Strip(list(text.render(self._rich_console))).crop(0, width)
```

- [ ] **Step 2: Add diff-added background to spec line rendering**

In `render_line`'s spec line section, modify the `cursor_bg` calculation (currently lines 230–235). Replace:

```python
        if is_cursor:
            cursor_bg = THEME["panel"]
        elif in_code or is_fence:
            cursor_bg = THEME["mantle"]
        else:
            cursor_bg = THEME["crust"]
```

With:

```python
        diff_added = (
            self.diff_state is not None
            and self.diff_state.is_active
            and self.diff_state.is_added(spec_idx)
        )
        if is_cursor:
            cursor_bg = THEME["panel"]
        elif diff_added:
            cursor_bg = THEME["diff_added_bg"]
        elif in_code or is_fence:
            cursor_bg = THEME["mantle"]
        else:
            cursor_bg = THEME["crust"]
```

- [ ] **Step 3: Add `+` marker in gutter for added lines**

In `render_line`'s line number section (lines 256–260), replace:

```python
        # Line number
        if self.show_line_numbers:
            num_str = f"{line_num:>{num_width}}  "
            text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=cursor_bg))
        else:
            text.append(" ", Style(bgcolor=cursor_bg))
```

With:

```python
        # Line number (with + marker for diff-added lines)
        if self.show_line_numbers:
            if diff_added:
                num_str = f"{line_num:>{num_width}} "
                text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=cursor_bg))
                text.append("+", Style(color=THEME["green"], bgcolor=cursor_bg))
            else:
                num_str = f"{line_num:>{num_width}}  "
                text.append(num_str, Style(color=THEME["text_dim"], dim=True, bgcolor=cursor_bg))
        else:
            if diff_added:
                text.append("+", Style(color=THEME["green"], bgcolor=cursor_bg))
            else:
                text.append(" ", Style(bgcolor=cursor_bg))
```

- [ ] **Step 4: Apply same diff_added logic to spec_wrap rows**

In render_line's `spec_wrap` section (lines 192–220), add `diff_added` check and adjust background. Replace the `cursor_bg` calculation:

```python
            if is_cursor:
                cursor_bg = THEME["panel"]
            elif in_code or is_fence:
                cursor_bg = THEME["mantle"]
            else:
                cursor_bg = THEME["crust"]
```

With:

```python
            diff_added = (
                self.diff_state is not None
                and self.diff_state.is_active
                and self.diff_state.is_added(spec_idx)
            )
            if is_cursor:
                cursor_bg = THEME["panel"]
            elif diff_added:
                cursor_bg = THEME["diff_added_bg"]
            elif in_code or is_fence:
                cursor_bg = THEME["mantle"]
            else:
                cursor_bg = THEME["crust"]
```

- [ ] **Step 5: Run all tests**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest -x -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add revspec/pager.py
git commit -m "feat: render ghost rows and diff-added styling in pager"
```

---

### Task 7: App integration — lifecycle, toggle, hunk navigation

**Files:**
- Modify: `revspec/app.py` (add `_diff_state`, modify `_do_reload`, `_approve`, add handlers)
- Modify: `revspec/hints.py:41-96` (add diff indicator to top bar)

- [ ] **Step 1: Add _diff_state attribute to RevspecApp.__init__**

Find the `__init__` or `on_mount` in `revspec/app.py`. Add the attribute initialization. Search for where `self._spec_mtime` is initialized and add nearby:

```python
        self._diff_state: DiffState | None = None
```

Add import at top of `app.py`:

```python
from .diff_state import DiffState
```

- [ ] **Step 2: Replace _do_reload with diff-aware version**

Replace the entire `_do_reload` method in `revspec/app.py` (lines 145–162) with this version. Key changes: (1) snapshot `old_lines` before reset, (2) split `new_content` once and reuse, (3) create `DiffState` after replay:

```python
    def _do_reload(self, new_content: str, new_mtime: float) -> None:
        """Shared reload logic — reset state, re-replay JSONL, reset UI."""
        old_lines = list(self.state.spec_lines)
        new_lines = new_content.split("\n")
        self.state.reset(new_lines)
        # Re-replay JSONL to restore thread state
        if os.path.exists(self.jsonl_path):
            events, _ = read_events(self.jsonl_path)
            for t in replay_events_to_threads(events):
                self.state.threads.append(t)
                self.state._thread_by_id[t.id] = t
                self.state._thread_by_line[t.line] = t
        self._spec_mtime = new_mtime
        self._spec_mtime_changed = False
        self.search_query = None
        self._jump_list = JumpList()
        self._heading_index.rebuild(new_lines)
        if self.pager_widget:
            self.pager_widget.invalidate_table_cache()
        self._watcher_service.init_offset()
        # Compute diff between old and new spec
        diff = DiffState(old_lines, new_lines)
        if diff.has_diff():
            self._diff_state = diff
        else:
            self._diff_state = None
        if self.pager_widget:
            self.pager_widget.diff_state = self._diff_state
```

- [ ] **Step 3: Clear DiffState on exit**

In `_exit_tui` method (line 916), add before `self.exit()`. This covers approve and all exit paths — safe since the app is terminating. No need to clear in `_approve()` separately since `_approve()` calls `_exit_tui()`:

```python
        self._diff_state = None
        if self.pager_widget:
            self.pager_widget.diff_state = None
```

- [ ] **Step 4: Add _toggle_diff handler**

Add method to `RevspecApp` (near the other toggle handlers around line 594):

```python
    def _toggle_diff(self) -> None:
        if self._diff_state is None:
            self._show_transient("No diff available", "warning")
            return
        active = self._diff_state.toggle()
        if self.pager_widget:
            self.pager_widget.diff_state = self._diff_state
            self.pager_widget.refresh_content()
        self._show_transient(f"Diff view {'on' if active else 'off'}")
```

- [ ] **Step 5: Add _next_hunk and _prev_hunk handlers**

Add methods to `RevspecApp` (near the thread navigation handlers):

```python
    def _next_hunk(self) -> None:
        if self._diff_state is None or not self._diff_state.has_diff():
            self._show_transient("No diff available", "warning")
            return
        target = self._diff_state.next_hunk(self.state.cursor_line)
        if target is None:
            target = self._diff_state.next_hunk(0)
            if target is None:
                return
            self._show_transient("Wrapped to first change", "info", 1.2)
        self._push_jump()
        self.state.cursor_line = target
        self._refresh()
        if not self._diff_state.is_added(target - 1):
            self._show_transient("Deletion above", "info", 1.2)

    def _prev_hunk(self) -> None:
        if self._diff_state is None or not self._diff_state.has_diff():
            self._show_transient("No diff available", "warning")
            return
        target = self._diff_state.prev_hunk(self.state.cursor_line)
        if target is None:
            target = self._diff_state.prev_hunk(self.state.line_count + 1)
            if target is None:
                return
            self._show_transient("Wrapped to last change", "info", 1.2)
        self._push_jump()
        self.state.cursor_line = target
        self._refresh()
        if not self._diff_state.is_added(target - 1):
            self._show_transient("Deletion above", "info", 1.2)
```

- [ ] **Step 6: Add :diff command handler to _process_command**

In `_process_command` (line 886), add after the `"wrap"` case (line 908):

```python
        elif result.action == "diff":
            self._toggle_diff()
```

- [ ] **Step 7: Add diff indicator to top bar**

In `revspec/hints.py`'s `build_top_bar` function, add a `diff_stats` parameter and render it. Modify the function signature (line 41):

```python
def build_top_bar(
    *,
    file_name: str,
    threads: list[Thread],
    unread_count: int,
    cursor_line: int,
    line_count: int,
    breadcrumb: str | None = None,
    mtime_changed: bool,
    diff_stats: tuple[int, int] | None = None,
) -> Text:
```

Add after the `mtime_changed` block (after line 77), before the position section:

```python
    # Diff indicator
    if diff_stats is not None:
        added, removed = diff_stats
        text.append("  \u00b7  ", Style(color=THEME["text_dim"]))
        text.append(f"[DIFF +{added} -{removed}]", Style(color=THEME["green"], bold=True))
```

- [ ] **Step 8: Update _top_bar_text in app.py to pass diff_stats**

In `revspec/app.py`'s `_top_bar_text` method (line 254), add the `diff_stats` kwarg:

```python
    def _top_bar_text(self) -> Text:
        return build_top_bar(
            file_name=Path(self.spec_file).name,
            threads=self.state.threads,
            unread_count=self.state.unread_count,
            cursor_line=self.state.cursor_line,
            line_count=self.state.line_count,
            breadcrumb=self._heading_index.breadcrumb(self.state.cursor_line),
            mtime_changed=self._spec_mtime_changed,
            diff_stats=self._diff_state.stats if self._diff_state and self._diff_state.is_active else None,
        )
```

- [ ] **Step 9: Run all tests**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest -x -q`
Expected: All PASS. Note: `test_hints.py` tests for `build_top_bar` may need updating if they check exact output — the new `diff_stats` param has a default of `None` so existing calls should still work.

- [ ] **Step 10: Commit**

```bash
git add revspec/app.py revspec/hints.py
git commit -m "feat: integrate DiffState lifecycle, toggle, hunk nav, top bar indicator"
```

---

### Task 8: Help screen and hint updates

**Files:**
- Modify: `revspec/overlays.py:379-438` (add diff keybindings to help text)

- [ ] **Step 1: Add diff keybindings to help screen**

In `revspec/overlays.py`'s `HelpScreen`, modify the help text string.

In the **Navigation** section (after the `''` line, around line 409), add:

```
  ]d/\\[d        Next/prev diff hunk
```

In the **Toggles** section (after `\\n`, around line 423), add:

```
  \\d           Toggle diff view
```

In the **Commands** section (after `:wrap`, around line 433), add:

```
  :diff        Toggle diff view (same as \\d)
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest -x -q`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add revspec/overlays.py
git commit -m "feat: add diff keybindings to help screen"
```

---

### Task 9: Update hints.py tests for diff_stats parameter

**Files:**
- Modify: `tests/test_hints.py` (add test for diff indicator in top bar)

- [ ] **Step 1: Write test for diff stats in top bar**

Append to `tests/test_hints.py`:

```python
class TestDiffIndicator:
    def test_top_bar_with_diff_stats(self):
        text = build_top_bar(
            file_name="spec.md",
            threads=[],
            unread_count=0,
            cursor_line=1,
            line_count=10,
            mtime_changed=False,
            diff_stats=(5, 3),
        )
        plain = text.plain
        assert "[DIFF +5 -3]" in plain

    def test_top_bar_without_diff_stats(self):
        text = build_top_bar(
            file_name="spec.md",
            threads=[],
            unread_count=0,
            cursor_line=1,
            line_count=10,
            mtime_changed=False,
        )
        plain = text.plain
        assert "DIFF" not in plain
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest tests/test_hints.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_hints.py
git commit -m "test: add diff indicator tests for top bar"
```

---

### Task 10: Update CLAUDE.md and final verification

**Files:**
- Modify: `CLAUDE.md` (update architecture, keybinding reference, test count, features)

- [ ] **Step 1: Run full test suite and count**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest -v 2>&1 | tail -5`
Note the total test count.

- [ ] **Step 2: Update CLAUDE.md**

Add to the Architecture table:

```
  diff_state.py        # DiffState — line-level diff computation between spec versions
```

Add to **Features > Core** list:

```
- Inline diff view after spec reload: removed lines as red ghost rows, added lines with green background, `+`/`-` gutter markers, toggle `\d`, hunk navigation `]d`/`[d`, `[DIFF +N -M]` top bar indicator
```

Update the **Keybinding reference** tables:

Normal mode — add row:
```
| \d | Toggle diff view | — |
| ]d | Next diff hunk | — |
| [d | Previous diff hunk | — |
```

Toggles — add row:
```
| \d | Toggle diff view |
```

Command mode — add row:
```
| :diff | Toggle diff view (same as \d) |
```

Update test count from 391 to new count.

Update **Files Changed** section in the architecture list (remove old count placeholder).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with diff view feature"
```

- [ ] **Step 4: Run full test suite one final time**

Run: `cd /Users/tuephan/repo/revspec-py && python -m pytest -x -q`
Expected: All PASS with no regressions
