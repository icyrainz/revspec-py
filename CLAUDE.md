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
- Dev: `pip install -e .` for editable install

## Architecture

```
revspec_tui/
  cli.py          # Entry point, arg parsing
  app.py          # Main Textual App — pager, overlays, key handling
  state.py        # ReviewState — cursor, threads, navigation
  protocol.py     # JSONL live event protocol (read/write/replay)
  theme.py        # Catppuccin Mocha color scheme
```

## JSONL Protocol

The JSONL protocol is **identical** to the TypeScript version. Both implementations read/write the same `spec.review.jsonl` format, so the AI integration (`revspec watch` / `revspec reply`) works with either TUI.

Event types: `comment`, `reply`, `resolve`, `unresolve`, `approve`, `delete`, `submit`, `session-end`, `round`

Each event is a single JSON line with `type`, `author`, `ts` fields, plus type-specific fields (`threadId`, `line`, `text`).

## Current state (prototype)

### Working (needs verification against TS behavior)
- Full-screen pager with line numbers, gutter thread indicators, cursor highlight
- Basic markdown syntax highlighting (headings, code blocks, lists, blockquotes)
- Vim-style navigation: j/k, Ctrl+D/U, gg/G
- Multi-key sequences: dd (delete thread), ]t/[t (next/prev thread), ]1/[1 (heading jump)
- Comment input modal (c key) — create new threads, reply to existing
- Thread list modal (t key) — navigate between threads
- Search modal (/ key) with n/N cycling, smartcase
- Command mode (:q, :q!, :wrap, :{line})
- Confirm dialogs for destructive actions
- Help screen (? key)
- JSONL protocol: read, write, replay — fully compatible with TypeScript version
- Resolve/unresolve threads (r key)
- Approve (A) and Submit (S)
- Status bars: top (file + thread counts) and bottom (position + hints)
- Search highlighting in pager

### Not yet implemented (required for parity)
- **Live watcher** — file polling for AI replies (see `src/cli/watch.ts`). Watch handles three exit conditions: approve > submit > session-end (priority order). Crash recovery: watch detects pending unprocessed `submit` and re-outputs resolved thread summaries.
- **Reply CLI subcommand** — `revspec reply <file.md> <threadId> "<text>"` (see `src/cli/reply.ts`)
- **Watch CLI subcommand** — `revspec watch <file.md>` (see `src/cli/watch.ts`)
- **Submit spinner** — modal spinner while waiting for AI to rewrite spec, polls spec mtime, cancellable (see `src/tui/spinner.ts`)
- **Spec reload** — detect spec file changes after submit, reload content, clear threads, reset state (see submit handler in `src/tui/app.ts` lines 770-820)
- **Spec mutation guard** — detect if spec file was modified externally, show warning in top bar (see `src/tui/app.ts` lines 119-125)
- **Jump list** — Ctrl+O/I forward/backward jump history, '' swap, mirrors vim :jumps (see `src/tui/app.ts` lines 161-184)
- **Thread popup persistence** — comment dialog stays open after submit for conversation flow; reply appends message to dialog, doesn't dismiss (see `src/tui/comment-input.ts`)
- **Thread popup vim modes** — normal mode (j/k scroll, blur textarea) vs insert mode (i/a to focus textarea); Ctrl+D/U scroll in normal mode (see `src/tui/comment-input.ts`)
- **Thread popup resolve toggle** — r key in thread popup toggles resolve, auto-advances to next thread on resolve (see `onResolve` in `src/tui/app.ts`)
- **H/M/L keys** — screen-relative cursor positioning using visualRowToSpecLine (see `src/tui/app.ts` lines 187-193, 925-944)
- **zz** — center cursor on screen (see `src/tui/app.ts` lines 663-670)
- **'' (jump back)** — swap between current and last jump position (see `src/tui/app.ts` lines 909-922)
- **]r/[r** — next/prev unread thread (see state.ts nextUnreadThread/prevUnreadThread)
- **R** — resolve all pending threads (see `src/tui/app.ts` lines 731-744)
- **Line wrapping** — :wrap toggle with proper visual-row-to-spec-line mapping (see countExtraVisualLines in `src/tui/pager.ts`)
- **Transient messages** — timed status bar notifications with icon support (info/warn/success), auto-clear after timeout (see showTransient in `src/tui/app.ts`)
- **Unread indicators** — bold yellow gutter █ for unread AI replies (see pager rendering)
- **Thread preview in bottom bar** — when cursor is on a line with a thread, show first message preview + reply count + status (see `src/tui/app.ts` lines 131-141)
- **Live watcher integration** — real-time AI reply handling, flash notification for AI replies when not viewing that thread (see `src/tui/app.ts` lines 63-81)
- **Markdown-aware table rendering** — box-drawing characters for tables (see `src/tui/ui/markdown.ts` lines 234-292)
- **Code-block-aware rendering** — track in_code_block state, different styling inside fenced blocks
- **Incremental search** — search preview updates pager highlighting as you type (see onPreview in search overlay)
- **Tests** — unit tests for state and protocol, integration tests for CLI subcommands

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
| :{N} | Jump to line number |

### Overlay keys
| Context | Key | Action |
|---------|-----|--------|
| Any overlay | Ctrl+C | Force dismiss |
| Comment popup | Tab | Submit comment |
| Comment popup | Esc | Cancel/dismiss |
| Comment popup | i/a | Enter insert mode |
| Comment popup | Escape (in insert) | Return to normal mode |
| Thread list | j/k | Navigate |
| Thread list | Enter | Go to thread |
| Thread list | Esc | Dismiss |
| Search | Enter | Accept match |
| Search | Esc | Cancel |
| Confirm | y/Enter | Confirm |
| Confirm | n/Esc | Cancel |

## Conventions (must match the TypeScript version exactly)

- Tab to submit in all text inputs (works through tmux)
- Destructive actions need confirmation (dd double-tap, approve confirm dialog)
- Thread popup uses vim-style normal/insert modes (blur textarea in normal)
- Hint bars use `[key] action` bracket format — all labels defined in keymap
- Consistent dismiss/confirm keys: `y/Enter` to confirm, `q/Esc` to dismiss (all popups)
- No inline comment previews in pager — gutter indicators only: ▌ active thread, █ unread AI reply, = resolved
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
| Pager rendering | `src/tui/pager.ts` | `revspec_tui/app.py` (SpecPager class) |
| Comment input | `src/tui/comment-input.ts` | `revspec_tui/app.py` (CommentScreen class) |
| Search overlay | `src/tui/search.ts` | `revspec_tui/app.py` (SearchScreen class) |
| Thread list | `src/tui/thread-list.ts` | `revspec_tui/app.py` (ThreadListScreen class) |
| Confirm dialog | `src/tui/confirm.ts` | `revspec_tui/app.py` (ConfirmScreen class) |
| Help screen | `src/tui/help.ts` | `revspec_tui/app.py` (HelpScreen class) |
| Spinner | `src/tui/spinner.ts` | not yet implemented |
| Status bars | `src/tui/status-bar.ts` | `revspec_tui/app.py` (top/bottom bar methods) |
| Keybind registry | `src/tui/ui/keybinds.ts` | `revspec_tui/app.py` (inline) |
| Markdown rendering | `src/tui/ui/markdown.ts` | `revspec_tui/app.py` (SpecPager._line_style) |
| Hint bar | `src/tui/ui/hint-bar.ts` | `revspec_tui/app.py` (inline) |
| Live watcher | `src/tui/live-watcher.ts` | not yet implemented |
| CLI watch | `src/cli/watch.ts` | not yet implemented |
| CLI reply | `src/cli/reply.ts` | not yet implemented |
| CLI entry | `bin/revspec.ts` | `revspec_tui/cli.py` |
