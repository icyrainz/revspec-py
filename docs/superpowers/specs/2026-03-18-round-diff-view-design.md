# Round Diff View — Design Spec

## Problem

After each submit/rewrite cycle, the reviewer sees the full updated spec but has no way to tell what changed. They waste time re-reading unchanged content to find the AI's modifications. This is the most-requested feature across similar tools.

## Solution

Show a unified diff view inline in the pager after a spec reload. Removed lines appear as red-tinted ghost rows with `-` prefix, added/changed lines appear with green-tinted background and `+` prefix. Unchanged lines render normally. The diff is auto-shown on reload and persists until approve. A `\d` toggle hides/shows it.

## Design

### DiffState class

New file: `revspec/diff_state.py`

Encapsulates all diff computation and query logic. The pager and app only interact through this interface.

```python
class DiffState:
    """Computes and exposes line-level diff between two spec versions."""

    def __init__(self, old_lines: list[str], new_lines: list[str]):
        # Uses difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        # autojunk=False prevents blank lines (common in markdown) from being
        # treated as junk, which shifts diff boundaries by one line.
        #
        # Populates:
        #   _added: set[int]  — 0-based new-file line indices that are new or changed
        #   _removed_blocks: dict[int, list[str]]  — maps new-file index to removed
        #       lines that should appear BEFORE that index. Key len(new_lines) holds
        #       removals at the end of the file.
        #   _hunk_starts: list[int]  — sorted list of new-file indices where diff
        #       hunks begin (first added or first line after a removed block)
        #   _stats: tuple[int, int]  — (added_count, removed_count)
        #   _is_active: bool  — starts True

    def is_added(self, new_idx: int) -> bool:
        """True if this new-file line was added or changed."""

    def removed_lines_before(self, new_idx: int) -> list[str]:
        """Returns removed lines that should appear before new_idx. Empty list if none."""

    def has_diff(self) -> bool:
        """True if any lines differ between old and new."""

    def toggle(self) -> bool:
        """Flip active state. Returns new state."""

    @property
    def is_active(self) -> bool:
        """Whether diff annotations are currently visible."""

    @property
    def stats(self) -> tuple[int, int]:
        """Returns (added_count, removed_count)."""

    def next_hunk(self, current_spec_line: int) -> int | None:
        """Returns spec line (1-based) of next diff hunk after current_spec_line, or None."""

    def prev_hunk(self, current_spec_line: int) -> int | None:
        """Returns spec line (1-based) of previous diff hunk before current_spec_line, or None."""
```

**Diff algorithm**: `difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)` from stdlib. `get_opcodes()` returns operations: `equal`, `replace`, `insert`, `delete`. We iterate these to populate `_added`, `_removed_blocks`, and `_hunk_starts`:

- `equal(i1, i2, j1, j2)` — no action
- `insert(i1, i2, j1, j2)` — mark `new_lines[j1:j2]` as added, record `j1` as hunk start
- `delete(i1, i2, j1, j2)` — store `old_lines[i1:i2]` as removed block before position `j1`, record `j1` as hunk start
- `replace(i1, i2, j1, j2)` — store `old_lines[i1:i2]` as removed block before `j1`, mark `new_lines[j1:j2]` as added, record `j1` as hunk start

**No key collision in `_removed_blocks`**: `get_opcodes()` returns non-overlapping, contiguous ranges. Adjacent deletes are coalesced. Two opcodes cannot map to the same `j1` key.

### Lifecycle

`RevspecApp` holds `self._diff_state: DiffState | None`, initialized to `None`.

**Created** in `_do_reload()`:
1. Before `state.reset(new_lines)`, snapshot `old_lines = list(self.state.spec_lines)`
2. After reset + replay, create `DiffState(old_lines, new_lines)`
3. If `diff_state.has_diff()` is False, set `self._diff_state = None` and show transient `"Spec reloaded — no changes detected"`
4. If diff exists, set `self._diff_state = diff_state` (starts active). The top bar `[DIFF +N -M]` indicator provides persistent change counts — no diff stats in transient messages. Existing transients remain: `"Spec rewritten — review cleared"` (submit path) and `"Spec reloaded"` (Ctrl+R path)

**Applies to all reload triggers**: submit polling, Ctrl+R manual reload — any reload where content changed produces a diff.

**Multi-round behavior**: On a second submit within the same session, `_do_reload()` snapshots the current spec (which was the previous rewrite) and creates a new `DiffState` comparing it to the latest rewrite. Each round diffs against the immediately previous version.

**Cleared** to `None`:
- On approve (`_approve()`) — the spec is finalized, nothing to diff
- On initial app load — no previous version exists

### Pager Access to DiffState

`SpecPager` has a `diff_state: DiffState | None` attribute, set by the app before calling `refresh_content()`. The pager reads this during `rebuild_visual_model()` and `render_line()`. The app sets it:

```python
self.pager_widget.diff_state = self._diff_state
self.pager_widget.refresh_content()  # triggers rebuild_visual_model()
```

This avoids the pager reaching up to the app (`self.app._diff_state`), keeping coupling clean.

### Visual Model Integration

In `pager.py`'s `rebuild_visual_model()`, when `diff_state` is active, interleave ghost rows.

**New row types**:
- `("diff_removed", text)` — a non-interactive ghost row
- `("diff_removed_wrap", text, segment)` — continuation row for long removed lines when wrap is enabled

**Build logic** — ghost rows are inserted before each spec line and before the `_spec_to_visual` assignment, so the mapping naturally accounts for ghost rows. Both the table path and non-table path need ghost row insertion:

```python
for i, line in enumerate(spec_lines):
    # Ghost rows BEFORE this spec line
    if diff_state and diff_state.is_active:
        for removed_text in diff_state.removed_lines_before(i):
            rows.append(("diff_removed", removed_text))
            # Wrap ghost rows at ghost content width
            ghost_content_width = width - ghost_gutter_width
            if wrap_width and ghost_content_width > 0 and len(removed_text) > ghost_content_width:
                extra = (len(removed_text) - 1) // ghost_content_width
                for seg in range(1, extra + 1):
                    rows.append(("diff_removed_wrap", removed_text, seg))

    # Table path or non-table path — see table rendering rule below
    # _spec_to_visual assignment happens HERE — after ghost rows, before spec row append
    spec_to_vis[i + 1] = len(rows)
    rows.append(("spec", i))
    # ... existing wrap logic ...

# Trailing removed lines after the last spec line
if diff_state and diff_state.is_active:
    for removed_text in diff_state.removed_lines_before(len(spec_lines)):
        rows.append(("diff_removed", removed_text))
```

**Tables with diffs**: If any line in a table block has a diff (is in `_added`, or has `removed_lines_before` it), the entire table is rendered as **raw pipe-delimited text** — no box-drawing borders, no `scan_table_blocks` formatting. Ghost rows appear naturally between raw table lines. Tables with zero diffs keep their box-drawing rendering. This avoids both visual corruption and silent suppression of changes.

Implementation: during `rebuild_visual_model()`, check `table_has_diff(block, diff_state)` — if any line in the block range is added or has removals before it, skip the table path and use the regular non-table path for those lines. The `_table_blocks` cache is not modified — `scan_table_blocks` still identifies tables normally. The diff check is a conditional skip at render-time only.

**Mapping impact**:
- `_spec_to_visual`: unchanged logic — computed after ghost rows are inserted, so it correctly points to the `("spec", i)` row
- `spec_line_at_visual_row(y)`: for ghost rows, resolve to the **next** spec line (scan forward). Uses a precomputed `_spec_row_indices: list[int]` (sorted visual row indices of all `("spec", ...)` rows) built during `rebuild_visual_model()`, with `bisect_left` for `O(log n)` lookup. Resolution rule: `bisect_left(_spec_row_indices, y)` gives the index of the first spec row at or after `y`. If the result index equals `len(_spec_row_indices)` (ghost rows after the last spec line — trailing removals), fall back to the **last** spec line. **Never returns `None`** — always resolves to a valid spec line number. This is required because `H`/`M`/`L` key handlers call `max(1, spec_line_at_visual_row(...))` which would crash on `None`.
- `visual_row_for_cursor()`: unchanged — cursor only targets spec lines

### Rendering

In `render_line(y)`, the ghost row branch must come **before** the `("spec", ...)` fallthrough, since the default destructuring `_kind, spec_idx = row` would crash on `("diff_removed", text)` where `row[1]` is a string, not an int.

**Dispatch order**:
1. `("table_border", ...)` — existing
2. `("diff_removed", text)` / `("diff_removed_wrap", text, seg)` — **new, before spec**
3. `("spec_wrap", ...)` — existing
4. `("spec", idx)` — existing (with diff-added styling when applicable)

**Ghost rows (`diff_removed` / `diff_removed_wrap`)**:
- Background: `THEME["diff_removed_bg"]` (dark red, `#3b1a1e`)
- Gutter width: `ghost_gutter_width` equals the spec line `gutter_total` (cursor + gutter icon + line number width) so content columns align perfectly between ghost rows and spec rows
- Gutter layout: `[space][space][-][padded_spaces]` — column 0 is space (no cursor on ghost rows), column 1 is space (no gutter icon), column 2 is `-` colored `THEME["red"]`, remaining columns are spaces to fill `ghost_gutter_width`. This ensures the `-` marker aligns with the `+` marker on added spec lines (which sits at column 2 in `[cursor][gutter_icon][+][line_num]`)
- Content rendered as plain text (no markdown styling)
- Full pager width

**Added spec lines** (real spec lines where `diff_state.is_added(idx)` is True):
- Background: `THEME["diff_added_bg"]` (dark green, `#1a3b1e`), **except** when cursor is on this line — cursor background `THEME["panel"]` takes priority so the cursor position is always clear
- Gutter layout: `[cursor][gutter_icon][+][line_num]` — the `+` replaces the space before the line number, colored `THEME["green"]`
- All normal interactions: cursor, gutter indicators, commenting, search
- Markdown rendering applied normally

**Unchanged spec lines**: No diff styling. Completely normal rendering.

### Theme

Two new colors in `theme.py`:

```python
"diff_added_bg": "#1a3b1e",    # subtle dark green background
"diff_removed_bg": "#3b1a1e",  # subtle dark red background
```

Muted enough to not overwhelm content. The `+`/`-` markers in `THEME["green"]`/`THEME["red"]` provide a secondary visual signal.

### Toggle & Keybinding

**Registry entry** in `key_dispatch.py`:
```python
KeySequence("backslashd", "\\d", "diff", "_toggle_diff"),
```

**Handler** in `app.py`:
```python
def _toggle_diff(self):
    if self._diff_state is None:
        self._show_transient("No diff available", "warning")
        return
    active = self._diff_state.toggle()
    self.pager_widget.diff_state = self._diff_state
    self.pager_widget.refresh_content()  # triggers rebuild_visual_model()
    self._show_transient(f"Diff view {'on' if active else 'off'}")
```

Note: `refresh_content()` calls `rebuild_visual_model()` then `refresh()`, which is required because ghost rows must be added/removed from `_visual_rows` — a simple repaint would not change the visual model.

**Auto-show**: `DiffState` starts with `_is_active = True`. Diff is visible immediately after reload.

**Hint bar**: `\` pending key shows `[\d] diff` alongside `[\w] wrap` and `[\n] lines`.

**Top bar**: When diff is active, show `[DIFF +N -M]` indicator in green in the top status bar, where N/M come from `diff_state.stats`.

**Command alias**: `:diff` toggles diff view, consistent with `:wrap`, `:help`, `:resolve`, etc.

### Hunk Navigation

**Registry entries** in `key_dispatch.py`:
```python
KeySequence("bracketrightd", "]d", "diff→", "_next_hunk"),
KeySequence("bracketleftd", "[d", "←diff", "_prev_hunk"),
```

**Handlers** in `app.py`:
```python
def _next_hunk(self):
    if self._diff_state is None or not self._diff_state.has_diff():
        self._show_transient("No diff available", "warning")
        return
    target = self._diff_state.next_hunk(self.state.cursor_line)
    if target is None:
        # Wrap to first hunk (consistent with ]t/]r wrapping)
        target = self._diff_state.next_hunk(0)
        if target is None:
            return
        self._show_transient("Wrapped to first change", "info", 1.2)
    self._push_jump()
    self.state.cursor_line = target
    self._refresh()
    # For pure-delete hunks, cursor lands on the line after deletion
    if not self._diff_state.is_added(target - 1):
        self._show_transient("Deletion above", "info", 1.2)

def _prev_hunk(self):
    if self._diff_state is None or not self._diff_state.has_diff():
        self._show_transient("No diff available", "warning")
        return
    target = self._diff_state.prev_hunk(self.state.cursor_line)
    if target is None:
        # Wrap to last hunk (consistent with [t/[r wrapping)
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

Hunk navigation works even when diff view is toggled off — it jumps to changed lines regardless of whether the visual diff overlay is displayed. Navigation wraps around with transient notification, consistent with `]t`/`[t` and `]r`/`[r`. For pure-delete hunks (no added lines at the target), cursor lands on the line after the deletion with a `"Deletion above"` hint — ghost rows are visible above the cursor.

### Navigation

Ghost rows are invisible to all navigation and interaction:

- **Cursor** (`j`/`k`): moves by spec line, skips ghost rows
- **Search** (`/`, `n`/`N`): searches only real spec lines
- **Comments** (`c`): only on real spec lines
- **Thread jumps** (`]t`/`[t`, `]r`/`[r`): operates on spec line indices
- **Hunk jumps** (`]d`/`[d`): jumps to next/prev diff hunk start (spec line)
- **Line jump** (`:15`): jumps to spec line 15, unaffected by ghost row count
- **Screen positions** (`H`/`M`/`L`): resolve ghost rows to nearest spec line via `spec_line_at_visual_row` (scan forward/backward)
- **Scroll**: Textual's ScrollView handles viewport scrolling. Ghost rows are visible as you scroll through but cursor never stops on them.

### Edge Cases

- **Empty diff**: `has_diff()` returns False — no diff state created, transient message `"Spec reloaded — no changes detected"`
- **Full rewrite**: All lines get `+`/`-` treatment — correct behavior, reviewer should see everything changed
- **Wrap + diff**: Ghost rows wrap using `diff_removed_wrap` row type. Ghost rows have a narrower gutter (no line number, no cursor) so their effective content width differs from spec rows — wrap at `ghost_content_width = width - ghost_gutter_width`
- **Tables in removed lines**: Rendered as plain text — no table box-drawing for ghost rows
- **Tables with diffs**: Entire table rendered as raw pipe-delimited text (no box-drawing) so ghost rows fit naturally. Tables with no diffs keep box-drawing
- **Scroll position**: Cursor resets to line 1 on reload (existing behavior)
- **Thread line drift**: After a rewrite, threads replayed from JSONL reference old line numbers which may no longer match. This is a pre-existing issue (#1 on the suggestion list: "Comment anchor drift") — the diff view makes it more visible but does not introduce it. Out of scope for this feature.

## Files Changed

| File | Change |
|------|--------|
| `revspec/diff_state.py` | **New** — DiffState class with diff computation, queries, hunk tracking, stats |
| `revspec/pager.py` | Add ghost row types to visual model, render diff styling, `spec_line_at_visual_row` ghost handling |
| `revspec/app.py` | Create/clear DiffState on reload/approve, `_toggle_diff`/`_next_hunk`/`_prev_hunk` handlers |
| `revspec/key_dispatch.py` | Add `\d`, `]d`, `[d` to SEQUENCE_REGISTRY |
| `revspec/theme.py` | Add `diff_added_bg`, `diff_removed_bg` colors |
| `revspec/hints.py` | Add `[\d] diff` to `\` pending hints, `[]d] diff` to `]`/`[` pending hints |
| `revspec/commands.py` | Add `:diff` command alias |
| `revspec/renderer.py` | Minor — pass diff-added bg to line rendering |
| `revspec/overlays.py` | Add `\d`, `]d`, `[d` keybindings to help screen |
| `tests/test_diff_state.py` | **New** — unit tests for DiffState |

## Out of Scope

- Side-by-side diff view (future enhancement)
- Diff persistence across sessions (diff is in-memory only)
- Word-level diff highlighting within changed lines
- JSONL protocol changes (none needed)
- Comment anchor drift after rewrite (separate P0 item)
