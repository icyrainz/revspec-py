# Full Feature Parity: revspec Python/Textual Port

**Date:** 2026-03-16
**Status:** Draft
**Goal:** Implement all missing features to achieve 1:1 parity with the TypeScript/Bun version.

## Approach: Foundation-First

Build missing infrastructure first, then layer features on top. Six sequential batches, each building on the previous.

**Known limitation:** H/M/L (Batch 1) will be slightly incorrect for files with tables until table rendering (Batch 3) adds `count_extra_visual_lines()`. This is acceptable — correctness improves incrementally.

## Batch 1: Navigation Primitives + State Additions

Foundation that many later features depend on.

### 1.1 Jump List (Ctrl+O/I, '' swap)

**TS ref:** `app.ts:161-184`, `app.ts:569-598`, `app.ts:909-922`

Add to `RevspecApp`:
- `_jump_list: list[int]` initialized to `[1]`
- `_jump_index: int = 0`
- `MAX_JUMP_LIST = 50`

`push_jump()`: record departure position before big jumps. Discard forward history when making a new jump from the middle. Don't push duplicates of the list tail.

`Ctrl+O`: jump backward. On first backward traversal from head, save current position without splicing forward history. Then decrement index and go to that line.

`Ctrl+I` / `Tab`: jump forward. Increment index if not at end.

**Textual Tab conflict:** In Textual, `Tab` has default focus-cycling behavior. Must intercept Tab in `on_key` before Textual consumes it. Tab only triggers jump-forward when no overlay is active (overlays use Tab for submit).

`''` (jump-back): swap between current position and last jump entry. Record current at jumpIndex, set jumpIndex to prevIdx, go to target.

**Key detail:** `push_jump()` is called BEFORE the cursor moves (saves departure). Checklist of ALL handlers needing `push_jump()`:
- `G` (goto-bottom) — existing handler, needs push_jump added
- `gg` (goto-top) — existing handler, needs push_jump added
- `n` / `N` (search next/prev) — existing handler
- `]t` / `[t` (next/prev thread) — existing handler
- `]r` / `[r` (next/prev unread) — new handler
- `]1-3` / `[1-3` (heading nav) — existing handler
- `:N` (command jump) — existing handler
- Thread list selection — existing callback
- Search result acceptance — existing callback

### 1.2 Unread Thread Navigation (]r/[r)

**TS ref:** `review-state.ts:209-221`, `app.ts:855-877`

Add to `ReviewState`:
- `next_unread_thread() -> int | None`: filter threads by unread, find first after cursor, wrap to first.
- `prev_unread_thread() -> int | None`: filter by unread, find last before cursor, wrap to last.

Add key sequences `bracketrightr` and `bracketleftr` to `_handle_sequence`.

**Note:** Unlike ]t/[t, the TS unread navigation does NOT show wrap notifications. Just silently wraps or shows "No unread replies".

### 1.3 Resolve All Pending (R)

**TS ref:** `review-state.ts:65-71`, `app.ts:731-744`

Add `resolve_all_pending()` to `ReviewState` — only resolves threads with `status == "pending"` (AI-replied threads). Semantically different from `resolve_all()` which resolves everything for the approve gate.

Add `R` key handler: count pending, if 0 show "No pending threads". Otherwise resolve all pending, append resolve events for each, show transient with count.

### 1.4 H/M/L Screen-Relative Positioning

**TS ref:** `app.ts:924-944`, `app.ts:187-193`

Need scroll position to map visual rows to spec lines. In Textual, use `self.pager_widget.scroll_offset.y` for scroll top. Without line wrapping or tables, visual row = spec line - 1:
- H: `scroll_top + 1`
- M: `scroll_top + page_height // 2`
- L: `scroll_top + page_height - 1`

Clamp to `[1, line_count]`. Call `push_jump()` before moving.

After Batch 3 (tables + wrapping), this should use `visual_row_to_spec_line()` for proper mapping.

### 1.5 Fix zz (Center Cursor)

**TS ref:** `app.ts:663-670`

Current implementation just calls `_refresh()`. Should scroll so cursor is at vertical center:
```python
target_scroll = max(0, self.state.cursor_line - 1 - self.size.height // 2)
self.pager_widget.scroll_to(y=target_scroll)
```

### 1.6 Fix Existing Smartcase Bug in Pager

The pager's search highlighting at `app.py:87-88` always does case-insensitive matching (`lower()`). Should respect smartcase: if the search query contains uppercase, match case-sensitively. Fix both `render()` highlight check and `_append_highlighted()`.

### 1.7 Fix Confirm Dialog: Add q Key

**TS ref:** `keymap.ts` CONFIRM_HINTS

Current `ConfirmScreen` handles `n` and `escape` but not `q` for cancel. Add `q` to match TS behavior.

## Batch 2: Thread Popup Overhaul

The comment dialog is the most complex overlay. Current implementation is basic — needs vim normal/insert modes, persistence after submit, and resolve toggle.

### 2.1 Thread Popup Vim Modes

**TS ref:** `comment-input.ts:76-150`

Two modes: `insert` (textarea focused, typing) and `normal` (textarea blurred, keys are navigation).

**Insert mode keys:**
- `Escape` → enter normal mode
- `Tab` → submit comment text, append to conversation, clear textarea, enter normal mode
- All other keys → pass to textarea

**Normal mode keys:**
- `Escape` / `q` → dismiss (cancel)
- `i` / `c` → enter insert mode (focus textarea). Note: TS uses `i` and `c` (not `a` — CLAUDE.md keybinding table is inaccurate here, follow TS source)
- `r` → resolve toggle (triggers onResolve)
- `j/k` / `down/up` → scroll conversation
- `Ctrl+D/U` → scroll 5 lines
- `gg/G` → scroll top/bottom

**Mode indicator:** Change dialog border color (green = insert, blue = normal). Update hint bar text per mode.

**Start mode:** New thread → insert mode (start typing immediately). Existing thread → normal mode (read conversation first).

### 2.2 Thread Popup Persistence

**TS ref:** `comment-input.ts:91-95`, `app.ts:294-351`

After Tab submit:
- Text is submitted (onSubmit callback fires)
- Message is appended to the conversation display within the popup
- Textarea is cleared
- Mode switches to normal
- Popup stays open (NOT dismissed)

For new comments: after first submit, the overlay's thread reference updates to the newly created thread. Subsequent Tabs are replies to that thread.

For replies: message appends to conversation, stays open.

Dismissal only on: `Escape`/`q` in normal mode, or `Ctrl+C`.

### 2.3 Thread Popup Resolve Toggle

**TS ref:** `app.ts:325-343`

`r` key in normal mode within the popup:
1. Toggle resolve on the thread
2. Dismiss the overlay
3. If resolving (not reopening): auto-advance cursor to next thread
4. Refresh pager

### 2.4 Live Message Push Interface

**TS ref:** `app.ts:71-73`

Design the popup's `add_message()` method now — when called, append a new message widget to the conversation scroll area and scroll to bottom. Wire up to live watcher in Batch 5.

## Batch 3: Rendering Improvements

### 3.1 Code-Block-Aware Rendering

**TS ref:** `pager.ts:148-217`

Current `_line_style` partially handles this but uses `text_muted` for code block content. Fix:
- Fence lines (`` ``` ``) → dim (text_dim)
- Lines inside code blocks → green (`theme["green"]`), no markdown parsing
- Track `in_code_block` state across the full render pass (already started)

### 3.2 Markdown Table Rendering

**TS ref:** `markdown.ts:162-292`, `pager.ts:130-234`

Tables with `|` delimiters get box-drawing character borders.

**Algorithm:**
1. Pre-scan spec lines for table blocks (consecutive `|`-starting lines, skip if inside code block). Cache this — only recompute on spec load/reload.
2. For each table block: find separator row (`|---|---|`), calculate column widths from display-width of cells (strip inline markdown markers for width calc)
3. Render: top border (┌─┬─┐), header rows (bold), separator (├─┼─┤), data rows, bottom border (└─┴─┘)

**Impact on scroll mapping:** Table borders add extra visual lines. Port `countExtraVisualLines()` from `pager.ts:284-318` faithfully — it counts both table borders AND wrap continuation lines. Update H/M/L and zz to use this function.

### 3.3 Incremental Search Preview

**TS ref:** `search.ts:77-83`

As the user types in the search input (after 3+ characters), update pager highlighting live. Use Textual message or callback from SearchScreen to RevspecApp. Fire on every keystroke after 3 chars, pass `None` when below threshold.

### 3.4 Line Wrapping

**TS ref:** `pager.ts:61-117`, `app.ts:112-115`, `app.ts:273-278`

`:wrap` toggle. When enabled:
- Content wraps at terminal width minus gutter width
- Wrapped continuation lines get blank gutter
- `count_extra_visual_lines` accounts for wrap lines
- H/M/L and zz use `visual_row_to_spec_line()` mapping

Implement last in this batch due to interactions with table rendering and scroll mapping.

## Batch 4: Status Bar + Transient Messages + Thread List Fixes

### 4.1 Transient Message Icons

**TS ref:** `app.ts:154-159`, `status-bar.ts`

Add icon parameter to `_show_transient(message, icon=None, duration=1.5)`:
- `info` → blue prefix
- `warn` → yellow prefix
- `success` → green prefix

Fix timer management: track `_message_timer` handle, cancel previous before setting new one.

### 4.2 Thread Preview in Bottom Bar

**TS ref:** `app.ts:131-141`

When cursor is on a line with a thread and no transient message is active:
- Show first message text (truncated to ~60 chars with ellipsis `…`)
- Reply count: `(N replies)` or `(1 reply)`
- Thread status in brackets: `[open]`, `[resolved]`, etc.

Only show when `_message_timer` is not active.

### 4.3 Unread Indicators Polish

Fix pager gutter icon logic. Current code uses `STATUS_ICONS.get(thread.status)` which always shows `█` for pending. Should differentiate:
- Pending + unread → bold yellow `█`
- Pending + read → blue `▌` (same as open)
- Open → blue `▌`
- Resolved → green `=`

### 4.4 Spec Mutation Guard

**TS ref:** `app.ts:84-86`, `app.ts:119-125`

Record spec file mtime at startup. On each refresh, check if mtime changed. If so, set flag and show warning in top bar.

### 4.5 Top Bar Format Fix

**TS ref:** `status-bar.ts`

Current Python top bar diverges from TS. Fix to include:
- Resolved count as `X/Y resolved` (green if all, yellow otherwise)
- Unread reply count
- Spec-changed warning when mutation guard triggers

### 4.6 Thread List: Sort by Status + Filter Cycling

**TS ref:** `thread-list.ts:60-63`, `thread-list.ts:80-217`

Fix thread list to:
- Sort threads by status order (open=0, pending=1, resolved=2), then by line number
- Add `q` key to dismiss (in addition to Escape)
- Add `Ctrl+F` to cycle filter: all → active → resolved → all

### 4.7 Help Screen Update

After adding all new keybindings, update the `HelpScreen` content to include: jump list (Ctrl+O/I, ''), ]r/[r, R, H/M/L, zz, and thread popup modes.

## Batch 5: CLI Subcommands + Submit Flow

### 5.1 Reply CLI Subcommand

**TS ref:** `reply.ts`

`revspec reply <file.md> <threadId> "<text>"`

Validate spec path, derive JSONL path, validate thread ID exists, clean shell escaping artifacts (`\!` → `!`), append reply event with `author: "owner"`.

New file: `revspec_tui/reply.py`. Add subcommand routing to `cli.py`.

### 5.2 Watch CLI Subcommand

**TS ref:** `watch.ts`

`revspec watch <file.md>`

New file: `revspec_tui/watch.py`. Contains:
- `run_watch()` — main watch loop
- `process_new_events()` — event processing
- `format_watch_output()` / `format_submit_output()` — output formatting
- `find_current_round_start_index()` — round delimiter logic
- Lock/offset file management

**Use polling only** (500ms `os.stat` + file read). No `watchdog` dependency — matches the "no native dependencies" constraint in CLAUDE.md.

Add subcommand routing to `cli.py`. Support `REVSPEC_WATCH_NO_BLOCK=1` env var.

### 5.3 Submit Spinner

**TS ref:** `spinner.ts`

New file: `revspec_tui/spinner.py` (or inline in app.py if small enough).

Modal overlay: animated spinner (`|`, `/`, `-`, `\`), message, elapsed seconds. Cancellable with Ctrl+C. Timeout after 120s.

### 5.4 Fix Submit Flow: Add Unresolved Gate

**TS ref:** `app.ts:770-820`

Current `_submit()` just appends the event. Must wrap in `unresolvedGate()` pattern:
1. Check `state.can_approve()` — if unresolved threads, show confirm dialog
2. On confirm: resolve all, append resolve events, then proceed with submit
3. After submit event: show spinner, start polling spec mtime

### 5.5 Spec Reload After Submit

**TS ref:** `app.ts:796-819`

After submit, poll spec file mtime every 500ms. When it changes:
1. Read new spec content
2. `state.reset(new_lines)`
3. Update mtime tracking
4. Reset live watcher
5. Dismiss spinner
6. Clear search, reset jump list to `[1]`
7. Show transient "Spec rewritten — review cleared"

### 5.6 Live Watcher (TUI Integration)

**TS ref:** `live-watcher.ts`, `app.ts:63-81`

Background polling of JSONL for `owner` events. When AI replies arrive:
1. Call `state.add_owner_reply()` for each reply event
2. If thread popup is open for that thread, call `add_message()` on the popup
3. If viewing different thread, show transient "AI replied on line N"
4. Refresh pager

Use Textual's `set_interval(0.5, self._check_live_events)`.

## Batch 6: Tests

### 6.1 Unit Tests — State

Test `ReviewState`: add_comment, reply, resolve, resolve_all_pending, delete, next/prev thread, next/prev unread thread, heading navigation, can_approve, active_thread_count.

### 6.2 Unit Tests — Protocol

Test JSONL read/write/replay: event serialization, replay_events_to_threads, offset-based reading, malformed line handling.

### 6.3 Integration Tests — CLI

Test `revspec reply`: creates correct JSONL event. Test `revspec watch` with `REVSPEC_WATCH_NO_BLOCK=1`: processes events, formats output correctly.

### 6.4 Integration Tests — App

Textual provides `pilot` for testing apps. Test key sequences, overlay lifecycle, search behavior, thread popup modes.

## File Changes Summary

| File | Changes |
|------|---------|
| `revspec_tui/state.py` | Add `next_unread_thread`, `prev_unread_thread`, `resolve_all_pending` |
| `revspec_tui/app.py` | Jump list, H/M/L, zz fix, '', ]r/[r, R, smartcase fix, confirm q key, thread popup overhaul, table rendering, incremental search, line wrapping, transient icons, thread preview, mutation guard, top/bottom bar format fix, thread list sort+filter, help screen update, submit unresolved gate, spec reload, live watcher |
| `revspec_tui/cli.py` | Parse `watch` and `reply` subcommands, route to modules |
| `revspec_tui/reply.py` | New — reply subcommand implementation |
| `revspec_tui/watch.py` | New — watch subcommand implementation |
| `revspec_tui/spinner.py` | New — submit spinner overlay (if extracted) |
| `revspec_tui/protocol.py` | No changes needed |
| `revspec_tui/theme.py` | No changes needed |
| `tests/test_state.py` | New |
| `tests/test_protocol.py` | New |
| `tests/test_cli.py` | New |
| `tests/test_app.py` | New |

## Architectural Considerations

### app.py Size

Currently 930 lines. The thread popup overhaul and table rendering will push it significantly larger. Extract when it becomes unwieldy:
- `CommentScreen` → `revspec_tui/comment_screen.py` (with vim mode logic)
- Spinner → `revspec_tui/spinner.py`

### Performance

- **Table pre-scan:** Cache on spec load/reload only. Don't rescan on every render.
- **Live watcher polling:** 500ms via Textual's event loop (not a separate thread).
- **Render method:** Currently O(n) per keypress for entire document. Profile for large specs — consider viewport-only rendering if slow. Correctness first.
