# Revspec (Python)

Python/Textual implementation of [revspec](https://github.com/icyrainz/revspec) — a terminal-based spec review tool with real-time AI conversation.

## Project status

**Production-ready.** Full feature parity with the TypeScript/Bun version, plus Python-only UX improvements. The JSONL protocol is identical — both implementations read/write the same format, so the AI integration (`revspec watch` / `revspec reply`) works with either TUI.

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
revspec/
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

### Key sequence registry

All two-key sequences (e.g. `gg`, `]t`, `\w`) are defined in `_SEQUENCE_REGISTRY` — a single class-level list. Prefix keys, hint bar content, and dispatch are all derived automatically at init time. To add a new sequence, add one entry to the registry and one handler method.

## JSONL Protocol

The JSONL protocol is **identical** to the TypeScript version. Both implementations read/write the same `spec.review.jsonl` format, so the AI integration (`revspec watch` / `revspec reply`) works with either TUI.

Event types: `comment`, `reply`, `resolve`, `unresolve`, `approve`, `delete`, `submit`, `session-end`, `round`

Each event is a single JSON line with `type`, `author`, `ts` fields, plus type-specific fields (`threadId`, `line`, `text`).

## Features

### Core (full parity with TypeScript version)
- ScrollView pager with Line API virtual scrolling, cursor prefix `>`, gutter indicators (`█` for all states, color-coded)
- Markdown syntax highlighting (h1-h3 color-coded: blue/blue/mauve, code blocks green, blockquotes with │ prefix, list bullets with •, horizontal rules)
- Inline markdown rendering (bold, italic, code, links, strikethrough) via parse_inline_markdown()
- Vim-style navigation: j/k, Ctrl+D/U, gg/G, H/M/L, zz
- Multi-key sequences via registry: dd, ]t/[t, ]r/[r, ]1/[1, '', gg, zz, \w, \n
- Jump list: Ctrl+O/Ctrl+I/Tab forward/backward, '' swap
- Comment input modal (c key) with vim normal/insert modes, timestamps, title update on new thread, border title, colored message pipes, resolve stays open
- Thread list modal (t key) with sort/filter, wrap-around navigation, empty state
- Search modal (/ key) with n/N cycling, smartcase, incremental preview (3+ chars), red "No match"
- Command mode (:q, :q!, :wrap, :{line} with clamping)
- Confirm dialogs (mauve border, y/Enter confirm, q/Esc cancel)
- Help screen (? key) with j/k/gg/G/Ctrl+D/U scrolling
- Spinner modal on submit (80ms animation, Ctrl+C cancel, 120s wall-clock timeout)
- JSONL protocol: read, write, replay — fully compatible with TypeScript version
- Resolve/unresolve threads (r key), resolve all pending (R)
- Approve (A) and Submit (S) with spinner + spec reload polling
- Status bars: top (file, thread counts, unread, mutation guard, position, breadcrumb) and bottom (thread preview, position, context-sensitive hints with Rich Text styling)
- Transparent pager background (THEME["base"] = None, inherits terminal bg)
- Pending key hints in bottom bar with available options (e.g. `[gg] top`, `[]t] thread  []r] unread`)
- Transient messages with icon support (info/warn/success), bottom bar guard against overwrites
- Unread indicators (yellow gutter block)
- Spec mutation guard (external modification warning in top bar)
- Live watcher integration (AI reply push into open CommentScreen, flash suppression, offset advance, restart on reload)
- Markdown-aware table rendering with box-drawing characters
- Code-block-aware rendering with precomputed state map
- Line wrapping (\w or :wrap toggle with continuation rows in visual model)
- Watch CLI subcommand with crash recovery, JSONL truncation guard, lock management
- Reply CLI subcommand with thread validation, shell escape cleanup
- All overlay screens use event.stop() to prevent key leaking to main app
- Welcome hint on first launch (8s)

### Python-only improvements (to port back to Bun version)
- **Comment popup stays in insert mode after Tab submit** — chat-like flow; only Escape returns to normal mode
- **Comment popup resolve visual feedback** — border color changes on resolve (green=resolved, blue=open, mauve=insert), title shows `[OPEN]`/`[RESOLVED]`, hint bar shows `[r] reopen` vs `[r] resolve`
- **Ctrl+R to reload spec** — manual reload when spec modified externally. Top bar shows `"!! Spec changed externally (Ctrl+R to reload)"`
- **Toggle keybindings** — `\w` toggles line wrap, `\n` toggles line numbers
- **Command aliases** — `:submit`, `:approve`, `:help`, `:resolve`, `:reload`
- **Watcher detection on submit** — S checks for `.review.lock` before submitting. Warns if no watcher is active
- **Session-end cleanup** — watch process cleans up lock + offset files on session-end (not just approve). TUI cleans up offset file on exit when no watcher is running
- **Pending key hint bar** — shows available options instead of `...` (e.g. pressing `]` shows `[]t] thread  []r] unread  []1] h1  []2] h2  []3] h3`)

### Tests
206 total (state, protocol, markdown, watch, reply, bugfixes)

### Known issues / remaining work
- **Inline markdown in table cells** — table cell contents are rendered as plain text; `parse_inline_markdown()` is not applied inside `render_table_row()`
- **Word-wrap uses hard character breaks** — not word-aware; may diverge from TS version on wrapped lines containing spaces

## Complete keybinding reference

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
| Ctrl+R | Reload spec | — |
| Ctrl+C | Exit (session-end) | app.ts:563 |

### Toggles
| Key | Action |
|-----|--------|
| \w | Toggle line wrapping |
| \n | Toggle line numbers |

### Command mode
| Command | Action |
|---------|--------|
| :q | Quit (warns if unresolved) |
| :q! | Force quit |
| :qa, :wq, etc. | All quit variants supported |
| :wrap | Toggle line wrapping |
| :{N} | Jump to line number (clamps to range, rejects <=0) |
| :submit | Submit for rewrite (same as S) |
| :approve | Approve spec (same as A) |
| :resolve | Resolve thread (same as r) |
| :reload | Reload spec (same as Ctrl+R) |
| :help | Show help (same as ?) |

### Overlay keys
| Context | Key | Action |
|---------|-----|--------|
| Any overlay | Ctrl+C | Force dismiss |
| Comment popup | Tab | Submit comment (stays in insert mode) |
| Comment popup | Esc | Return to normal mode / dismiss |
| Comment popup | i/c | Enter insert mode |
| Comment popup | r | Resolve/reopen (normal mode) |
| Thread list | j/k | Navigate (wraps around) |
| Thread list | Enter | Go to thread |
| Thread list | Ctrl+F | Cycle filter (all/active/resolved) |
| Thread list | Esc | Dismiss |
| Search | Enter | Accept match |
| Search | Esc | Cancel |
| Confirm | y/Enter | Confirm |
| Confirm | q/Esc | Cancel |

## Conventions

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
- Comment popup border colors: blue=normal/open, mauve=insert, green=resolved

## Reference: TypeScript source → Python module mapping

| Feature | TypeScript source | Python module |
|---------|-------------------|---------------|
| Main TUI + keybindings | `src/tui/app.ts` | `revspec/app.py` |
| Review state | `src/state/review-state.ts` | `revspec/state.py` |
| JSONL protocol | `src/protocol/live-events.ts` | `revspec/protocol.py` |
| Protocol types | `src/protocol/types.ts` | `revspec/protocol.py` |
| Theme/colors | `src/tui/ui/theme.ts` | `revspec/theme.py` |
| Pager rendering | `src/tui/pager.ts` | `revspec/app.py` (SpecPager ScrollView) |
| Comment input | `src/tui/comment-input.ts` | `revspec/comment_screen.py` |
| Search overlay | `src/tui/search.ts` | `revspec/app.py` (SearchScreen class) |
| Thread list | `src/tui/thread-list.ts` | `revspec/app.py` (ThreadListScreen class) |
| Confirm dialog | `src/tui/confirm.ts` | `revspec/app.py` (ConfirmScreen class) |
| Help screen | `src/tui/help.ts` | `revspec/app.py` (HelpScreen class) |
| Spinner | `src/tui/spinner.ts` | `revspec/app.py` (SpinnerScreen class) |
| Status bars | `src/tui/status-bar.ts` | `revspec/app.py` (top/bottom bar methods) |
| Keybind registry | `src/tui/ui/keybinds.ts` | `revspec/app.py` (_SEQUENCE_REGISTRY) |
| Markdown rendering | `src/tui/ui/markdown.ts` | `revspec/markdown.py` + `app.py` (_line_style) |
| Hint bar | `src/tui/ui/hint-bar.ts` | `revspec/app.py` (inline) |
| Live watcher | `src/tui/live-watcher.ts` | `revspec/app.py` (_check_live_events) |
| CLI watch | `src/cli/watch.ts` | `revspec/watch.py` |
| CLI reply | `src/cli/reply.ts` | `revspec/reply.py` |
| CLI entry | `bin/revspec.ts` | `revspec/cli.py` |
