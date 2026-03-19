# Design: `session-start` Event for Multi-Session Watch

## Problem

When `revspec watch` starts on a file that has an `approve` event from a previous review session, it reads all events from offset 0, sees the old approve, and immediately returns "Review approved" instead of waiting for new events.

The watcher can't distinguish between:
- **Scenario 1**: Old approve from a completed previous session (should be ignored)
- **Scenario 3**: Current-session offline approve where watcher started late (should be processed)

Both scenarios present identically: no offset file, approve at EOF.

## Three scenarios the fix must handle

| # | Scenario | State | Correct behavior |
|---|----------|-------|-----------------|
| 1 | Fresh start after completed session | No offset file. JSONL ends with old approve. TUI reopened. | Wait for new events |
| 2 | Crash recovery | Offset file exists with valid byte position. Watcher crashed mid-session. | Recover missed approve/submit from offset |
| 3 | Offline approve | No offset file. Reviewer approved without watcher (e.g. network down). Same session. | Return "Review approved" |

## How competitors handle this

- **crit**: Avoids the problem entirely. Uses synchronous blocking (`tmux wait-for`) — agent blocks until TUI closes, then reads comments. No watcher, no polling, no sessions.
- **mdreview**: No event log. Mutable JSON sidecar + snapshot file. Rounds are implicit (diff current vs snapshot). Single-process only.
- **Neither tool has our architecture.** The append-only JSONL + async watcher pattern is unique to revspec.

## Solution: New `session-start` event type

### Event definition

A new event type `session-start` — the natural complement to the existing `session-end`.

Fields: `type`, `author`, `ts` only. No `threadId`, no `text`, no `round` number.

### Remove dead `round` event type

The `round` event type was defined in protocol.py but never written anywhere in the codebase. Removed `round` from `EventType`, `VALID_EVENT_TYPES`, its validation logic, and the `round` field from `LiveEvent` dataclass (along with references in `parse_event` and `append_event`).

### TUI side (app.py)

After replaying JSONL events on startup, write a `session-start` event:

```python
# After event replay in __init__
if events:
    last_event_type = events[-1].type
    if last_event_type != "session-start":
        append_event(self.jsonl_path, LiveEvent(
            type="session-start", author="reviewer",
            ts=int(time.time() * 1000),
        ))
```

Dedup rule: write on every TUI open **unless the last event is already `session-start`**. This is broader than "only after approve/session-end" because it also covers TUI crashes (where `session-end` was never written).

### Watcher side (watch.py)

Add `"session-start"` to boundary checks in two places:

**1. Crash recovery** (line 125 — `has_newer` check):
```python
has_newer = any(e.type in ("submit", "session-end", "session-start", "comment") for e in after)
```

**2. Normal event processing** (line 162 — approve handling):
```python
# Before processing approve, check if session-start follows it
last_approve_idx = _find_last_index(events, lambda e: e.type == "approve")
if last_approve_idx >= 0:
    after_approve = events[last_approve_idx + 1:]
    new_session_started = any(e.type == "session-start" for e in after_approve)
    if not new_session_started:
        # Process the approve (scenario 3: offline approve)
        ...
```

### Protocol side (protocol.py)

- Add `"session-start"` to `EventType` literal union
- Add `"session-start"` to `VALID_EVENT_TYPES` set
- Add to no-threadId-required whitelist (line 41)

## Scenario walkthrough

| Scenario | JSONL state | Watcher behavior |
|----------|-------------|-----------------|
| 1: Fresh start after completed session | `...approve, session-start` | Sees `session-start` after approve -> skip, wait for new events |
| 2: Crash recovery | Offset file exists -> resumes from offset | Unchanged (crash recovery path uses offset file) |
| 3: Offline approve | `...approve` (no `session-start`) | No `session-start` after approve -> processes it correctly |
| 4: TUI crash, reopen | `...comment, session-start` | No approve to recover -> waits for new events |
| 5: Open/close/open/close (no activity) | `...approve, session-start` (deduped) | One `session-start`, not four |
| 6: Watcher starts before TUI reopens | `...approve` (TUI hasn't opened yet) | No `session-start` -> processes approve (same as scenario 3, correct) |

## JSONL example across sessions

```jsonl
{"type": "comment", "author": "reviewer", "ts": 1000, "threadId": "abc1", "line": 5, "text": "fix this"}
{"type": "reply", "author": "owner", "ts": 2000, "threadId": "abc1", "text": "will do"}
{"type": "resolve", "author": "reviewer", "ts": 3000, "threadId": "abc1"}
{"type": "approve", "author": "reviewer", "ts": 4000}
{"type": "session-start", "author": "reviewer", "ts": 8000}
... new session comments ...
{"type": "approve", "author": "reviewer", "ts": 12000}
{"type": "session-start", "author": "reviewer", "ts": 15000}
```

## Backward compatibility

- The TypeScript version's JSONL parser silently drops unknown event types (same as Python's `is_valid_event` at line 33-34). No crash, no data corruption.
- `session-start` carries no thread state, so thread replay is unaffected in older versions.
- The TypeScript watcher would need the same fix if it has the same bug (likely does since the protocol is shared).

## Files to change

| File | Change |
|------|--------|
| `revspec/protocol.py` | Add `session-start`, remove `round` from `EventType`, `VALID_EVENT_TYPES`, validation, no-threadId whitelist |
| `revspec/app.py` | Write `session-start` after JSONL replay on startup |
| `revspec/watch.py` | Add `session-start` to boundary checks (crash recovery + normal flow) |
| `tests/test_watch.py` | Tests for scenarios 1, 3, 5, 6 |
| `tests/test_protocol.py` | Validation test for `session-start` event type |

## Verification

1. Run existing test suite — all 378 tests should pass (no regressions)
2. New test: write JSONL with approve, then session-start, run `revspec watch --no-block` -> should output nothing (scenario 1)
3. New test: write JSONL with approve only, run `revspec watch --no-block` -> should output "Review approved" (scenario 3)
4. Manual test: open TUI on file with old approve, verify session-start is written, verify watcher waits for new events
