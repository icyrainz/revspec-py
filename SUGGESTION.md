# Remaining Suggestions

Items from expert analysis and review rounds. Architecture refactor is complete.

## Quick Wins

| # | Improvement | Source | Effort |
|---|------------|--------|--------|
| 1 | **Count prefixes** — `5j`, `3G` should work | Vim | Low |
| 2 | **Width-based gutter** — `▏` open (white), `▐` pending (yellow), `█` resolved (green) — width + color | UX | Low |
| 3 | **Thread index dict** — replace `next(t for t in threads)` with O(1) lookup in state.py | Perf | Low |
| 4 | **Precompute heading index** — eliminates O(n) regex scan on every cursor move for breadcrumb | Perf | Low |
| 5 | **Search match count** — `"3 of 12 matches"` instead of clearing on no-match | UX, Vim | Low |
| 6 | **Move mode label to title bar** — `[INSERT]`/`[NORMAL]` in comment popup border title, hint bar stays pure `[key] action` | UX | Low |
| 7 | **Unify pending/unread color** — pager and thread list should both use `is_unread` for yellow, not `status == "pending"` | Review | Low |
| 8 | **Resolve-and-close** — `r` in comment popup resolves and dismisses immediately | UX | Low |
| 9 | **Context line in comment popup** — dimmed preview of the spec line below the title bar | UX | Low |
| 10 | **Thread list Enter opens comment** — jump to line AND open the comment popup in one action | UX | Low |

## Performance

| # | Improvement | Impact | Effort |
|---|------------|--------|--------|
| 1 | **Make `_check_live_events` async** — use Textual's `@work` to avoid blocking UI on large JSONL | Prevents 10-50ms freezes on poll | Medium |
| 2 | **Extract VisualModel** — testable class for `rebuild_visual_model()`, enable dirty-range invalidation instead of full rebuild on every keystroke | Needed at 1000+ line specs | Medium |
| 3 | **Batch ThreadListScreen rebuilds** — remove/mount all items at once instead of one-by-one async awaits | 50 threads = 100 DOM ops → ~5 | Low |
| 4 | **Precompile search regex** — avoid re-checking case sensitivity per render_line call | Minor render speedup | Low |
| 5 | **Dead event branches** — `_check_live_events` handles resolve/unresolve/delete but `poll()` filters to owner-only; these branches are unreachable. Remove or fix filter. | Code clarity | Low |

## Vim Power Features

| # | Feature | Why | Effort |
|---|---------|-----|--------|
| 1 | **Count prefixes** (`5j`, `3gg`) | Vim muscle memory, biggest friction point for power users | Medium |
| 2 | **Marks** (`m<char>`, `` `<char> ``) | Bookmark threads/lines, navigate complex reviews | Low |
| 3 | **`{`/`}` paragraph motions** | Jump by blank-line-separated blocks, natural for specs | Medium |
| 4 | **Fuzzy find threads** | Searchable thread list, "find threads mentioning X" | Medium |
| 5 | **Section folding** (`zc`/`zo`) | Collapse h2/h3 sections, reduce cognitive load on large specs | Medium |
| 6 | **Basic macros** (`q<char>`/`@<char>`) | Record/replay keystroke sequences for bulk operations | High |
| 7 | **`w`/`b`/`e` word motions** | Navigate by semantic units, not just lines | Medium |
| 8 | **`f`/`F`/`t`/`T` char search** | Rapid intra-line navigation | Medium |

## UX / Accessibility

| # | Improvement | Why | Effort |
|---|------------|-----|--------|
| 1 | **Spec diff on AI rewrite** | Show what changed after submit, auto-accept cosmetic fixes | Medium |
| 2 | **Spec mutation guard de-escalation** | Yellow "updated" instead of red "!!" — less alarming | Low |
| 3 | **Command mode autocomplete** | `:hel` → `:help`, show available commands on `:` | Medium |
| 4 | **Help screen sections** | Navigable tabs instead of monolithic wall of text | Medium |
| 5 | **Confirmation messages with consequences** | `"Permanent — edit .review.jsonl to undo"` on delete | Low |
| 6 | **Jump list visibility** | Show `[Ctrl+O] back` in hint bar when history exists | Low |
| 7 | **Thread list search** | `/` within thread list to filter by text | Medium |

## Product / Integration (longer term)

| # | Feature | Priority | Why |
|---|---------|----------|-----|
| 1 | **`.gitignore` auto-integration** | P0 | Prevent accidental commit of `.review.jsonl` |
| 2 | **`revspec repair` command** | P0 | Validate/fix corrupted JSONL |
| 3 | **GitHub Actions integration** | P1 | AI spec review in CI |
| 4 | **Export threads → PR comments** | P1 | Close the git workflow loop |
| 5 | **VSCode/Cursor extension** | P1 | One-click open spec in revspec |
| 6 | **Spec diff view** | P1 | Show what AI changed on rewrite |
| 7 | **Multi-file spec support** | P1 | `#include` or spec chains for large projects |
| 8 | **Session history + analytics** | P2 | "47 specs reviewed, avg 2.3 rounds" |
| 9 | **AI backend abstraction** | P2 | Pluggable (Claude, GPT, Ollama) |
| 10 | **Team workspaces** | P2 | Role-based access, network effects |

## Risks to Watch

| Risk | Mitigation |
|------|-----------|
| Textual framework abandonment | Monitor repo health; plan curses/blessed escape hatch |
| Bun/Python feature drift | 2-week sync cycle; shared test expectations |
| Performance at scale (1000+ lines) | `rebuild_visual_model` needs dirty-range invalidation |
| JSONL corruption on crash | Atomic writes, `revspec repair` command |
