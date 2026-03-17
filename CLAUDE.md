# Revspec (Python)

Python/Textual port of [revspec](https://github.com/icyrainz/revspec) — the TypeScript/Bun original.

## CRITICAL: Full Feature Parity Required

This is a 1:1 port of the Bun version. Every feature, keybinding, behavior, and UI detail in the TypeScript version MUST be replicated exactly. When in doubt, clone the original repo and read the source — it is the spec. Do not invent new behavior, skip features, or simplify interactions. The goal is that a user switching between the Bun and Python versions notices zero difference in functionality.

The original repo is at: `https://github.com/icyrainz/revspec`

**Before implementing any feature, read the corresponding TypeScript source file to understand the exact behavior.** The reference files section below maps Python modules to their TypeScript counterparts.

## Why this exists

The original revspec depends on Bun (via OpenTUI's bun:ffi bindings to Zig). Some environments block Bun executables, including standalone compiled binaries. This Python port uses Textual for the TUI layer, requiring only Python (which is universally available).

## Tech stack

- **Python 3.11+** — no native dependencies
- **Textual** — TUI framework (pip install, pure Python)
- **Rich** — terminal rendering (Textual dependency)
- Package: `revspec` on PyPI
- Install: `pipx install revspec` or `pip install revspec`
- Run: `revspec <file.md>`
- Dev: `uv venv && uv pip install hatchling editables && uv pip install -e . --no-build-isolation`

## Architecture

```
revspec_tui/
  cli.py              # Entry point, arg parsing, subcommand routing
  app.py              # Main Textual App — ScrollView pager, overlays, key handling
  state.py            # ReviewState — cursor, threads, navigation
  protocol.py         # JSONL live event protocol (read/write/replay)
  theme.py            # Catppuccin Mocha color scheme
  comment_screen.py   # Thread popup with vim normal/insert modes
  markdown.py         # Table parsing, rendering, word-wrap helpers
  watch.py            # CLI watch subcommand (AI event monitor)
  reply.py            # CLI reply subcommand (AI reply writer)
```

### Pager architecture

`SpecPager` extends Textual's `ScrollView` using the Line API:
- `rebuild_visual_model()` builds a list of visual rows: `("spec", idx)`, `("spec_wrap", idx, seg)`, `("table_border", idx, pos)`
- `render_line(y)` renders a single visual row on demand — Textual's compositor calls this for each visible screen line
- `virtual_size` tells ScrollView the total content height
- Scrolling is native to ScrollView — no manual viewport math needed

## JSONL Protocol

The JSONL protocol is **identical** to the TypeScript version. Both implementations read/write the same `spec.review.jsonl` format, so the AI integration (`revspec watch` / `revspec reply`) works with either TUI.

Event types: `comment`, `reply`, `resolve`, `unresolve`, `approve`, `delete`, `submit`, `session-end`, `round`

Each event is a single JSON line with `type`, `author`, `ts` fields, plus type-specific fields (`threadId`, `line`, `text`).

## Current state

### Implemented (full parity achieved)
- ScrollView pager with Line API virtual scrolling, cursor prefix `>`, gutter indicators (`█` for all states, color-coded)
- Markdown syntax highlighting (h1-h3 color-coded: blue/blue/mauve, code blocks green, blockquotes italic)
- Vim-style navigation: j/k, Ctrl+D/U, gg/G, H/M/L, zz
- Multi-key sequences: dd, ]t/[t, ]r/[r, ]1/[1, '', gg, zz
- Jump list: Ctrl+O/Ctrl+I/Tab forward/backward, '' swap
- Comment input modal (c key) with vim normal/insert modes, timestamps, title update on new thread
- Thread list modal (t key) with sort/filter, wrap-around navigation, empty state
- Search modal (/ key) with n/N cycling, smartcase, incremental preview (3+ chars), red "No match"
- Command mode (:q, :q!, :wrap, :{line} with clamping)
- Confirm dialogs (mauve border, y/Enter confirm, q/Esc cancel)
- Help screen (? key) with j/k/gg/G/Ctrl+D/U scrolling
- Spinner modal on submit (80ms animation, Ctrl+C cancel, 120s wall-clock timeout)
- JSONL protocol: read, write, replay — fully compatible with TypeScript version
- Resolve/unresolve threads (r key), resolve all pending (R)
- Approve (A) and Submit (S) with spinner + spec reload polling
- Status bars: top (file, thread counts, unread, mutation guard, position, breadcrumb) and bottom (thread preview, position, hints)
- Transient messages with icon support (info/warn/success), bottom bar guard against overwrites
- Unread indicators (yellow gutter block)
- Spec mutation guard (external modification warning in top bar)
- Live watcher integration (AI reply push into open CommentScreen, flash suppression, offset advance, restart on reload)
- Markdown-aware table rendering with box-drawing characters
- Code-block-aware rendering with precomputed state map
- Line wrapping (:wrap toggle with continuation rows in visual model)
- Watch CLI subcommand with crash recovery, JSONL truncation guard, lock management
- Reply CLI subcommand with thread validation, shell escape cleanup
- All overlay screens use event.stop() to prevent key leaking to main app
- Welcome hint on first launch (8s)
- Tests: 144 total (state, protocol, markdown, watch, reply)

### Known issues / remaining work
- **Inline markdown rendering** — bold/italic/code/links render as raw text with markers visible; TS parses inline segments with per-segment styling
- **Pending key hint** — TS shows partial sequence (e.g. `g`) in bottom bar while waiting for second key
- **Pager background** — `THEME["base"]` is hardcoded `#1e1e2e` vs TS `undefined` (transparent/inherit terminal bg)

## Complete keybinding reference (must match exactly)

### Normal mode
| Key | Action | TS Reference |
|-----|--------|-------------|
| j / down | Cursor down | app.ts:623 |
| k / up | Cursor up | app.ts:630 |
| Ctrl+D | Half-page down | app.ts:637 |
| Ctrl+U | Half-page up | app.ts:645 |
| G | Go to bottom | app.ts:651 |
| gg | Go to top | app.ts:657 |
| H | Screen top | app.ts:925 |
| M | Screen middle | app.ts:932 |
| L | Screen bottom | app.ts:938 |
| zz | Center cursor | app.ts:663 |
| n | Search next | app.ts:671 |
| N | Search prev | app.ts:690 |
| c | Comment/reply on current line | app.ts:709 |
| t | Thread list | app.ts:712 |
| r | Resolve/reopen thread | app.ts:715 |
| R | Resolve all pending | app.ts:731 |
| dd | Delete thread (with confirm) | app.ts:746 |
| S | Submit for rewrite | app.ts:770 |
| A | Approve (exit) | app.ts:822 |
| ]t | Next thread | app.ts:827 |
| [t | Previous thread | app.ts:843 |
| ]r | Next unread thread | app.ts:855 |
| [r | Previous unread thread | app.ts:866 |
| ]1 / [1 | Next/prev h1 heading | app.ts:879 |
| ]2 / [2 | Next/prev h2 heading | app.ts:879 |
| ]3 / [3 | Next/prev h3 heading | app.ts:879 |
| '' | Jump back (swap positions) | app.ts:909 |
| Ctrl+O | Jump list backward | app.ts:569 |
| Ctrl+I / Tab | Jump list forward | app.ts:590 |
| / | Open search | app.ts:948 |
| : | Command mode | app.ts:951 |
| ? | Help screen | app.ts:946 |
| Escape | Clear search highlights | app.ts:601 |
| Ctrl+C | Exit (session-end) | app.ts:563 |

### Command mode
| Command | Action |
|---------|--------|
| :q | Quit (warns if unresolved) |
| :q! | Force quit |
| :qa, :wq, etc. | All quit variants supported |
| :wrap | Toggle line wrapping |
| :{N} | Jump to line number (clamps to range, rejects <=0) |

### Overlay keys
| Context | Key | Action |
|---------|-----|--------|
| Any overlay | Ctrl+C | Force dismiss |
| Comment popup | Tab | Submit comment |
| Comment popup | Esc | Cancel/dismiss |
| Comment popup | i/c | Enter insert mode |
| Comment popup | Escape (in insert) | Return to normal mode |
| Thread list | j/k | Navigate (wraps around) |
| Thread list | Enter | Go to thread |
| Thread list | Ctrl+F | Cycle filter (all/active/resolved) |
| Thread list | Esc | Dismiss |
| Search | Enter | Accept match |
| Search | Esc | Cancel |
| Confirm | y/Enter | Confirm |
| Confirm | q/Esc | Cancel |

## Conventions (must match the TypeScript version exactly)

- Tab to submit in all text inputs (works through tmux)
- Destructive actions need confirmation (dd double-tap, approve confirm dialog)
- Thread popup uses vim-style normal/insert modes (blur textarea in normal)
- Hint bars use `[key] action` bracket format — all labels defined in keymap
- Consistent dismiss/confirm keys: `y/Enter` to confirm, `q/Esc` to dismiss (all popups)
- No inline comment previews in pager — gutter indicators only: █ for all states (white=open, yellow=unread, green=resolved)
- Thread IDs use nanoid (8-char alphanumeric) — no sequential t1/t2
- No review JSON — JSONL is the single source of truth
- `submit` events in JSONL act as round delimiters
- S submits for rewrite (stays in TUI), A approves (exits)
- `:q` warns if unresolved threads, `:q!` force quits
- Search is smartcase (case-sensitive only if query contains uppercase)
- Search wraps around with notification ("Search wrapped to top/bottom")
- Thread navigation wraps around with notification ("Wrapped to first/last thread")

## Reference: TypeScript source → Python module mapping

| Feature | TypeScript source | Python module |
|---------|-------------------|---------------|
| Main TUI + keybindings | `src/tui/app.ts` | `revspec_tui/app.py` |
| Review state | `src/state/review-state.ts` | `revspec_tui/state.py` |
| JSONL protocol | `src/protocol/live-events.ts` | `revspec_tui/protocol.py` |
| Protocol types | `src/protocol/types.ts` | `revspec_tui/protocol.py` |
| Theme/colors | `src/tui/ui/theme.ts` | `revspec_tui/theme.py` |
| Pager rendering | `src/tui/pager.ts` | `revspec_tui/app.py` (SpecPager ScrollView) |
| Comment input | `src/tui/comment-input.ts` | `revspec_tui/comment_screen.py` |
| Search overlay | `src/tui/search.ts` | `revspec_tui/app.py` (SearchScreen class) |
| Thread list | `src/tui/thread-list.ts` | `revspec_tui/app.py` (ThreadListScreen class) |
| Confirm dialog | `src/tui/confirm.ts` | `revspec_tui/app.py` (ConfirmScreen class) |
| Help screen | `src/tui/help.ts` | `revspec_tui/app.py` (HelpScreen class) |
| Spinner | `src/tui/spinner.ts` | `revspec_tui/app.py` (SpinnerScreen class) |
| Status bars | `src/tui/status-bar.ts` | `revspec_tui/app.py` (top/bottom bar methods) |
| Keybind registry | `src/tui/ui/keybinds.ts` | `revspec_tui/app.py` (inline) |
| Markdown rendering | `src/tui/ui/markdown.ts` | `revspec_tui/markdown.py` + `app.py` (_line_style) |
| Hint bar | `src/tui/ui/hint-bar.ts` | `revspec_tui/app.py` (inline) |
| Live watcher | `src/tui/live-watcher.ts` | `revspec_tui/app.py` (_check_live_events) |
| CLI watch | `src/cli/watch.ts` | `revspec_tui/watch.py` |
| CLI reply | `src/cli/reply.ts` | `revspec_tui/reply.py` |
| CLI entry | `bin/revspec.ts` | `revspec_tui/cli.py` |
