# Revspec (Python)

Python/Textual port of [revspec](https://github.com/icyrainz/revspec) — the TypeScript/Bun original.

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

### Working
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

### Not yet implemented
- **Live watcher** — file polling for AI replies (the `watch` and `reply` CLI subcommands)
- **Submit spinner** — show progress while waiting for AI to rewrite spec
- **Spec reload** — detect spec file changes after submit, reload content
- **Jump list** — Ctrl+O/I forward/backward jump history
- **Thread popup persistence** — keep comment dialog open after submit for conversation flow
- **Scroll-to-cursor refinement** — current scroll behavior is rough
- **H/M/L keys** — screen-relative cursor positioning
- **zz** — center cursor on screen (mapped but needs scroll logic)
- **'' (jump back)** — swap between current and last position
- **]r/[r** — next/prev unread thread
- **R** — resolve all pending threads
- **Line wrapping** — :wrap toggle
- **Transient messages** — timed status bar notifications (partially working)
- **Unread indicators** — bold yellow gutter for unread AI replies
- **Tests** — unit tests for state and protocol, integration tests

## Conventions (match the TypeScript version)

- Tab to submit in all text inputs
- Destructive actions need confirmation (dd double-tap, approve confirm dialog)
- Thread popup uses vim-style normal/insert modes
- Hint bars use `[key] action` bracket format
- Consistent dismiss/confirm keys: `y/Enter` to confirm, `q/Esc` to dismiss
- Gutter indicators only: ▌ active thread, █ unread AI reply, = resolved
- Thread IDs use nanoid (8-char alphanumeric)
- No review JSON — JSONL is the single source of truth
- `submit` events in JSONL act as round delimiters
- S submits for rewrite (stays in TUI), A approves (exits)
- `:q` warns if unresolved threads, `:q!` force quits

## Reference

- Original TypeScript source: https://github.com/icyrainz/revspec
- Key files to reference for behavior parity:
  - `src/tui/app.ts` — main TUI logic, keybindings, overlay management
  - `src/state/review-state.ts` — state management
  - `src/protocol/live-events.ts` — JSONL protocol
  - `src/tui/ui/theme.ts` — color scheme
  - `src/tui/pager.ts` — line rendering with markdown highlighting
  - `src/tui/comment-input.ts` — thread popup with vim normal/insert modes
  - `src/cli/watch.ts` — live watcher for AI integration
  - `src/cli/reply.ts` — AI reply submission
