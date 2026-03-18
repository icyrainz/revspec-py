---
name: revspec
description: Launch revspec to review a spec document with real-time AI feedback. Use when the user says /revspec, "review the spec", "let me review this", or after generating a spec/design document that needs human review. Also use when a brainstorming or writing-plans skill produces a markdown spec file. Works on any markdown file (ADRs, READMEs, etc.) but primarily designed for spec review. Works even when no .md file exists yet (inline or plan mode content gets saved to a file first). Supports `/revspec <path>` to review a specific file and resuming previous review sessions.
---

# Revspec — Live Spec Review

Launch revspec to let the human review a spec document with real-time AI conversation. The reviewer comments on specific lines, you reply instantly, and the discussion continues until the spec is approved. Also works on any markdown file.

## When to Use

- After writing or updating a spec/design document
- When the user explicitly asks to review a spec
- After the brainstorming or writing-plans skill produces a `.md` file
- When the user provides a file path: `/revspec <path>`

## How It Works

You and the human communicate through revspec's CLI:
- `revspec watch <file.md>` — blocks until the reviewer adds comments, then returns them
- `revspec reply <file.md> <threadId> "<text>"` — sends your reply (appears in the TUI instantly)

The reviewer stays in the revspec TUI for the entire session. You run the watch/reply loop.

## Step 1: Find or Create the File

**If a file path was provided** (e.g., `/revspec docs/my-spec.md`):
Use it directly — skip the search below.

**Otherwise**, detect which file was recently created or modified in this conversation:
- Files written to `docs/superpowers/specs/*.md`
- The last `.md` file you created or edited

**If the content was written inline** (proposed in conversation output or plan mode, never saved to a file):
1. Save the content to a `.md` file — use `docs/superpowers/specs/<topic>.md` or a reasonable path in the project
2. Confirm the file path with the user before proceeding

If ambiguous, ask the user which file to review.

**Resuming a previous review:** Check if a `.review.jsonl` file already exists for the target file (e.g., `spec.review.jsonl`). If it does, the TUI will restore previous threads automatically — let the user know they're resuming where they left off.

## Step 2: Launch Revspec

Check if running inside tmux:

```bash
echo $TMUX
```

**If tmux is available:**
```bash
# Split from Claude Code's own pane (not the user's active window)
tmux split-window -t "$TMUX_PANE" -v "revspec <spec-file>"
```

**If no tmux, but on macOS:** detect the terminal and open a new window:

```bash
echo $TERM_PROGRAM
```

| `$TERM_PROGRAM` | Launch command |
|---|---|
| `Apple_Terminal` | `osascript -e 'tell application "Terminal" to do script "revspec <spec-file>"'` |
| `iTerm.app` | `osascript -e 'tell application "iTerm2" to create window with default profile command "revspec <spec-file>"'` |
| `WezTerm` | `wezterm start -- revspec <spec-file>` |
| `ghostty` | `ghostty -e revspec <spec-file>` |
| Other/unknown | Fall back to `osascript` with Terminal.app |

**Otherwise (not macOS):**
Tell the user: "Please run in another terminal: `revspec <spec-file>`"

## Step 3: Run the Watch/Reply Loop

Start watching for reviewer comments:

```bash
revspec watch <spec-file>
```

This blocks until the reviewer adds comments. When it returns, you'll see output like:

```
=== New Comments ===
Thread: x1a3f (line 14)
  Context:
      12: The system uses polling...
    > 14: it sends a notification via webhook.
      16: resource state.
  [reviewer]: this is unclear
  To reply: revspec reply spec.md x1a3f "<your reply>"

When done replying, run: revspec watch spec.md
```

**For each comment:** Read the context, understand the concern, and reply thoughtfully:

```bash
revspec reply <spec-file> x1a3f "Good point. I'll clarify — it uses polling to detect changes, then sends a webhook notification to downstream services."
```

After replying to all comments, run `revspec watch` again to wait for the next batch.

**If watch returns "Session ended. Reviewer exited revspec."** — the reviewer closed the TUI. Stop and wait — the user can invoke `/revspec` again later.

**Important:** Your replies should be substantive — address the concern, explain your reasoning, or acknowledge the change you'll make. Don't just say "noted" or "will fix."

## Step 4: Handle Submit, Session End, or Approval

The watch loop ends in one of three ways:

### Submit (reviewer pressed `S`)

Watch returns resolved thread summaries:

```
=== Submit: Rewrite Requested ===

Resolved threads:
  x1a3f (line 14): "this is unclear"
    → AI: "I'll clarify the polling vs webhook distinction."

Rewrite the spec incorporating the above, then run: revspec watch spec.md
```

1. Read the current spec and compare against the resolved threads
2. If changes are needed: rewrite the spec and save — this triggers the TUI to reload automatically
3. If the spec already reflects the feedback (e.g., crash recovery): skip rewrite
4. Run `revspec watch` again — the reviewer is still in the TUI and will see the new content

**Important:** Watch may re-output the submit summary on crash recovery. Always verify whether the spec already incorporates the feedback before rewriting.

### Session ended (reviewer exited with `:q`)

The reviewer closed the TUI. Stop and wait — the user can invoke `/revspec` again later.

### Approved (reviewer pressed `A`)

Watch returns:
```
Review approved.
```

The spec is finalized. Report: "Spec approved and finalized at `<spec-file>`. Ready to proceed with implementation."

## Thread Status Meanings

- **Open** — under discussion, AI replied, reviewer hasn't responded yet
- **Pending** — owner replied, waiting for reviewer to read
- **Resolved** — reviewer acknowledged the plan, AI should make the change

## Loop Summary

```
1. Launch revspec on spec file
2. Watch for comments
3. Reply to each comment
4. Watch again (repeat 2-3 until submit/session-end/approval)
5. On submit: verify and rewrite spec if needed (triggers TUI reload), go to step 2
6. On session-end: stop, user will invoke /revspec again if needed
7. On approval: spec is finalized, done
```

## Tips

- Read the full thread history in the watch output before replying — the reviewer may have added context across multiple messages
- When rewriting the spec after approval, address every resolved thread — the reviewer trusted you to incorporate their feedback
- Keep replies concise but complete — the reviewer can see them instantly and will follow up if needed
- If a comment is about a section you're unsure about, say so honestly — "I'm not sure about the best approach here. Options are X or Y — which do you prefer?"
