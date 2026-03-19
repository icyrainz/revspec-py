# Remaining Suggestions

Unified priority order based on expert analysis, review rounds, and competitive research (mdreview, crit, tuicr, MRSF, md-feedback, Plannotator, Remark, claude-review). Architecture refactor is complete.

## P0 — Do First

High impact or foundational. Fixes broken workflows, prevents data issues, or trivial effort.

| # | Feature | Category | Why | Effort |
|---|---------|----------|-----|--------|
| 1 | **Comment anchor drift** — store `selectedText` in comment events, re-anchor after rewrite (exact match → line fallback → fuzzy → orphan). Orphaned comments surfaced in thread list, not gutter | Core | Without this, comments point to wrong lines after every rewrite — breaks multi-round reviews | Medium |
| 2 | **Round diff view** — `\d` toggle shows inline diff (green added, red removed) between previous and current spec. Store previous content on submit | Core | Most-requested pattern across all similar tools — reviewers waste time re-reading unchanged content | Medium |
| 3 | **`.gitignore` auto-integration** — add `.review.jsonl` to `.gitignore` on first write | Integration | Prevents accidental commit of review data | Low |
| 4 | **`revspec repair` command** — validate/fix corrupted JSONL | Integration | Data integrity — JSONL corruption on crash is a known risk | Low |
| 5 | **Unify pending/unread color** — pager and thread list should both use `is_unread` for yellow, not `status == "pending"` | Bugfix | Inconsistent gutter colors between views | Low |
| 6 | **Dead event branches** — `_check_live_events` handles resolve/unresolve/delete but `poll()` filters to owner-only; these branches are unreachable. Remove or fix filter | Code quality | Unreachable code hides real bugs | Low |

## P1 — High Value

Significant UX or workflow improvement. Mix of quick wins and medium-effort features.

| # | Feature | Category | Why | Effort |
|---|---------|----------|-----|--------|
| 7 | **Count prefixes** — `5j`, `3G`, `3gg` should work | Vim | Biggest friction point for vim power users | Medium |
| 8 | **Search match count** — `"3 of 12 matches"` in status bar | Vim, UX | Standard vim behavior, low effort | Low |
| 9 | **Comment types** — ISSUE / SUGGESTION / QUESTION / NOTE, cycle with Tab during input. Color-coded in thread view. Optional severity (high/medium/low) | Core | Helps AI prioritize; structured feedback more actionable than free-text | Medium |
| 10 | **Structured clipboard export** — `:export` or `\e` copies all unresolved comments in LLM-optimized format (numbered, line refs, types, thread context) | Core | Enables offline workflow without watcher — paste into any AI tool | Low |
| 11 | **Session persistence** — auto-save cursor, scroll, search, toggles to `.review.session`. Restore on relaunch | UX | Terminal crash or quit mid-review loses all navigation state | Low |
| 12 | **CI exit codes** — `revspec --ci spec.md` returns 0=approved, 1=unresolved, 2=no review | Integration | Enables `revspec --ci spec.md && deploy` | Low |
| 13 | **Context line in comment popup** — dimmed preview of the spec line below the title bar | UX | Orients the reviewer without dismissing the popup | Low |
| 14 | **Thread list Enter opens comment** — jump to line AND open the comment popup in one action | UX | Two-step flow (Enter, then c) is unnecessary friction | Low |
| 15 | **Resolve-and-close** — `r` in comment popup resolves and dismisses immediately | UX | Current flow requires extra keystrokes to dismiss | Low |
| 16 | **Width-based gutter** — `▏` open (white), `▐` pending (yellow), `█` resolved (green) — width + color | UX | Visual distinction beyond color alone | Low |
| 17 | **Spec mutation guard de-escalation** — yellow "updated" instead of red "!!" | UX | Less alarming for normal AI rewrite workflow | Low |
| 18 | **Thread index dict** — replace `next(t for t in threads)` with O(1) lookup in state.py | Perf | Foundation for perf at scale | Low |
| 19 | **Precompute heading index** — eliminates O(n) regex scan on every cursor move for breadcrumb | Perf | Noticeable on 500+ line specs | Low |
| 20 | **Move mode label to title bar** — `[INSERT]`/`[NORMAL]` in comment popup border title, hint bar stays pure `[key] action` | UX | Cleaner separation of concerns | Low |

## P2 — Medium Value

Good improvements, moderate effort or narrower audience.

| # | Feature | Category | Why | Effort |
|---|---------|----------|-----|--------|
| 21 | **Line-range comments** — `v` visual mode to select lines, then `c` to comment on range. Store `startLine`/`endLine` in event | Core | Sometimes feedback applies to a block, not a single line | Medium |
| 22 | **Marks** — `m<char>` to set, `` `<char> `` to jump | Vim | Bookmark threads/lines, navigate complex reviews | Low |
| 23 | **`{`/`}` paragraph motions** — jump by blank-line-separated blocks | Vim | Natural for spec documents | Medium |
| 24 | **Fuzzy find / thread list search** — `/` within thread list to filter by text | Vim, UX | "Find threads mentioning X" | Medium |
| 25 | **Make `_check_live_events` async** — use Textual's `@work` to avoid blocking UI on large JSONL | Perf | Prevents 10-50ms freezes on poll | Medium |
| 26 | **Extract VisualModel** — testable class for `rebuild_visual_model()`, enable dirty-range invalidation | Perf | Needed at 1000+ line specs | Medium |
| 27 | **Command mode autocomplete** — `:hel` → `:help`, show available commands on `:` | UX | Discoverability | Medium |
| 28 | **Help screen sections** — navigable tabs instead of monolithic wall of text | UX | Current help screen is overwhelming | Medium |
| 29 | **Export threads → PR comments** — push review threads to GitHub PR | Integration | Close the git workflow loop | Medium |
| 30 | **Comment event trail** — show resolve/unresolve/reply history in thread popup (data already in JSONL) | UX | Transparency on comment lifecycle | Low |
| 31 | **Quality gates** — `:approve` blocks if unresolved ISSUE-type comments exist, `:approve!` overrides | Core | Prevents premature approval (requires #9 comment types) | Low |
| 32 | **Confirmation messages with consequences** — `"Permanent — edit .review.jsonl to undo"` on delete | UX | Users should know what they're doing | Low |
| 33 | **Jump list visibility** — show `[Ctrl+O] back` in hint bar when history exists | UX | Discoverability | Low |
| 34 | **Batch ThreadListScreen rebuilds** — remove/mount all items at once instead of one-by-one | Perf | 50 threads = 100 DOM ops → ~5 | Low |
| 35 | **Precompile search regex** — avoid re-checking case sensitivity per render_line call | Perf | Minor render speedup | Low |

## P3 — Longer Term

Large effort, niche audience, or depends on ecosystem maturity.

| # | Feature | Category | Why | Effort |
|---|---------|----------|-----|--------|
| 36 | **Section folding** — `zc`/`zo` to collapse h2/h3 sections | Vim | Reduce cognitive load on large specs | Medium |
| 37 | **`w`/`b`/`e` word motions** | Vim | Navigate by semantic units, not just lines | Medium |
| 38 | **`f`/`F`/`t`/`T` char search** | Vim | Rapid intra-line navigation | Medium |
| 39 | **Basic macros** — `q<char>`/`@<char>` record/replay | Vim | Bulk operations on threads | High |
| 40 | **MCP server** — expose `list_threads`, `get_thread`, `add_reply`, `resolve_thread` as MCP tools | Integration | Any MCP-capable agent can interact without custom scripting | High |
| 41 | **Multi-file review** — `revspec dir/` with `[f`/`]f` navigation, each file gets its own JSONL | Core | Large projects have multiple spec files | High |
| 42 | **Configurable keybindings** — TOML config at `~/.config/revspec/keys.toml` | UX | Non-vim users or different vim habits | Medium |
| 43 | **GitHub Actions integration** — AI spec review in CI (builds on #12 CI exit codes) | Integration | Automated review gating | Medium |
| 44 | **VSCode/Cursor extension** — one-click open spec in revspec | Integration | IDE integration for non-terminal users | Medium |
| 45 | **Session history + analytics** — "47 specs reviewed, avg 2.3 rounds" | Integration | Usage insights | Medium |
| 46 | **AI backend abstraction** — pluggable providers (Claude, GPT, Ollama) | Integration | Provider flexibility | Medium |
| 47 | **Team workspaces** — role-based access, network effects | Integration | Collaboration at scale | High |

## Risks to Watch

| Risk | Mitigation |
|------|-----------|
| Textual framework abandonment | Monitor repo health; plan curses/blessed escape hatch |
| Bun/Python feature drift | 2-week sync cycle; shared test expectations |
| Performance at scale (1000+ lines) | #26 VisualModel extraction + dirty-range invalidation |
| JSONL corruption on crash | #4 `revspec repair` command + atomic writes |
| Anchor drift after rewrite | #1 is P0 — without it multi-round reviews degrade |
