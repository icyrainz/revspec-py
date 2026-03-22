"""revspec watch — CLI subcommand for AI to monitor review events."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .protocol import read_events, replay_events_to_threads


def run_watch(spec_file: str) -> None:
    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    jsonl_path = spec_path.parent / (spec_path.stem + ".review.jsonl")
    offset_path = spec_path.parent / (spec_path.stem + ".review.offset")
    lock_path = spec_path.parent / (spec_path.stem + ".review.lock")

    _acquire_lock(lock_path)

    offset, last_submit_ts = _read_offset(offset_path)
    # Guard against truncated/recreated JSONL — reset if file is smaller than offset
    if jsonl_path.exists():
        if offset > jsonl_path.stat().st_size:
            offset = 0
            last_submit_ts = 0
    else:
        offset = 0
        last_submit_ts = 0
    spec_lines = spec_path.read_text(encoding="utf-8").split("\n")

    no_block = os.environ.get("REVSPEC_WATCH_NO_BLOCK") == "1"

    try:
        if no_block:
            result = _process_new_events(
                str(jsonl_path), str(offset_path), str(spec_path),
                spec_lines, offset, last_submit_ts, check_recovery=True,
            )
            if result.approved:
                sys.stdout.write(result.output)
                _cleanup(lock_path, offset_path)
            elif result.session_ended:
                sys.stdout.write(result.output)
                _cleanup(lock_path, offset_path)
            elif result.output:
                sys.stdout.write(result.output)
            return

        # Blocking mode: poll until events arrive
        first_poll = True
        while True:
            result = _process_new_events(
                str(jsonl_path), str(offset_path), str(spec_path),
                spec_lines, offset, last_submit_ts, check_recovery=first_poll,
            )
            first_poll = False

            if result.approved:
                sys.stdout.write(result.output)
                _cleanup(lock_path, offset_path)
                return

            if result.session_ended:
                sys.stdout.write(result.output)
                _cleanup(lock_path, offset_path)
                return

            if result.output:
                sys.stdout.write(result.output)
                return

            offset = result.new_offset
            _, last_submit_ts = _read_offset(offset_path)

            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _release_lock(lock_path)


# --- Internal helpers ---

class _ProcessResult:
    __slots__ = ("approved", "session_ended", "output", "new_offset")
    def __init__(self, approved=False, session_ended=False, output="", new_offset=0):
        self.approved = approved
        self.session_ended = session_ended
        self.output = output
        self.new_offset = new_offset


def _process_new_events(
    jsonl_path: str, offset_path: str, spec_path: str,
    spec_lines: list[str], offset: int, last_submit_ts: int,
    check_recovery: bool,
) -> _ProcessResult:
    if not os.path.exists(jsonl_path):
        return _ProcessResult(new_offset=offset)

    events, new_offset = read_events(jsonl_path, offset)

    # Full event history — read once on first use, reused across code paths
    _all_evts = None

    def _all_events():
        nonlocal _all_evts
        if _all_evts is None:
            _all_evts = read_events(jsonl_path, 0)
        return _all_evts

    # Crash recovery
    if not events and check_recovery:
        all_evts, eof_offset = _all_events()

        # Recover missed approve
        last_approve_idx = _find_last_index(all_evts, lambda e: e.type == "approve")
        if last_approve_idx >= 0:
            # Check no submit, session-end, session-start, or comment after the approve
            after = all_evts[last_approve_idx + 1:]
            has_newer = any(e.type in ("submit", "session-end", "session-start", "comment") for e in after)
            if not has_newer:
                # Only surface events from after the last submit, not full history
                last_submit_before = _find_last_index(
                    all_evts[:last_approve_idx], lambda e: e.type == "submit"
                )
                round_start = last_submit_before + 1 if last_submit_before >= 0 else 0
                round_events = all_evts[round_start:last_approve_idx]
                output = _format_approve_output(
                    round_events, spec_lines, spec_path,
                )
                _write_offset(offset_path, eof_offset, last_submit_ts)
                return _ProcessResult(approved=True, output=output, new_offset=eof_offset)

        # Recover missed submit
        last_submit_idx = _find_last_index(all_evts, lambda e: e.type == "submit")
        if last_submit_idx >= 0:
            last_submit_event = all_evts[last_submit_idx]
            if last_submit_event.ts == last_submit_ts:
                return _ProcessResult(new_offset=offset)
            after = all_evts[last_submit_idx + 1:]
            has_new = any(e.type in ("comment", "reply", "approve", "session-end", "session-start") for e in after)
            if not has_new:
                round_start = _find_current_round_start(all_evts)
                round_threads = replay_events_to_threads(all_evts[round_start:])
                resolved = [t for t in round_threads if t.status == "resolved"]
                output = _format_submit_output(resolved, spec_path)
                _write_offset(offset_path, eof_offset, last_submit_event.ts)
                return _ProcessResult(output=output, new_offset=eof_offset)
        return _ProcessResult(new_offset=offset)

    if not events:
        return _ProcessResult(new_offset=offset)

    _write_offset(offset_path, new_offset, last_submit_ts)

    # If batch contains a session-start, discard events before it (old session)
    last_session_start_idx = _find_last_index(events, lambda e: e.type == "session-start")
    if last_session_start_idx >= 0:
        events = events[last_session_start_idx + 1:]
        if not events:
            return _ProcessResult(new_offset=new_offset)

    # Priority: approve > submit > session-end
    if any(e.type == "approve" for e in events):
        all_evts, _ = _all_events()
        output = _format_approve_output(events, spec_lines, spec_path, all_events=all_evts)
        return _ProcessResult(approved=True, output=output, new_offset=new_offset)

    submit_event = next((e for e in reversed(events) if e.type == "submit"), None)
    if submit_event:
        all_evts, _ = _all_events()
        round_start = _find_current_round_start(all_evts)
        round_threads = replay_events_to_threads(all_evts[round_start:])
        resolved = [t for t in round_threads if t.status == "resolved"]
        output = _format_submit_output(resolved, spec_path)
        _write_offset(offset_path, new_offset, submit_event.ts)
        return _ProcessResult(output=output, new_offset=new_offset)

    if any(e.type == "session-end" for e in events):
        return _ProcessResult(
            output="Session ended. Reviewer exited revspec.\n",
            session_ended=True,
            new_offset=new_offset,
        )

    # Actionable events — comments and replies from reviewer
    actionable = [e for e in events if e.author == "reviewer" and e.type in ("comment", "reply")]
    if not actionable:
        return _ProcessResult(new_offset=new_offset)

    all_evts, _ = _all_events()
    all_threads = replay_events_to_threads(all_evts)
    threads_by_id = {t.id: t for t in all_threads}

    output = _format_watch_output(actionable, threads_by_id, spec_lines, spec_path)
    return _ProcessResult(output=output, new_offset=new_offset)


def _format_watch_output(events, threads_by_id, spec_lines, spec_path, approved=False):
    new_ids, reply_ids = [], []
    seen = set()
    for e in events:
        if not e.thread_id:
            continue
        if e.type == "comment" and e.thread_id not in seen:
            new_ids.append(e.thread_id)
            seen.add(e.thread_id)
        elif e.type == "reply" and e.thread_id not in reply_ids:
            reply_ids.append(e.thread_id)

    lines = []
    if new_ids:
        lines.append("=== New Comments ===")
        for tid in new_ids:
            t = threads_by_id.get(tid)
            if not t:
                continue
            lines.append(f"Thread: {tid} (line {t.line})")
            ctx = _get_context(spec_lines, t.line, 2)
            if ctx:
                lines.append("  Context:")
                lines.extend(f"    {c}" for c in ctx)
            for msg in t.messages:
                lines.append(f"  [{msg.author}]: {msg.text}")
            if not approved:
                lines.append(f"  To reply: revspec reply {spec_path} {tid} \"<your reply>\"")
            lines.append("")

    if reply_ids:
        lines.append("=== Replies ===")
        for tid in reply_ids:
            t = threads_by_id.get(tid)
            if not t:
                continue
            lines.append(f"Thread: {tid} (line {t.line})")
            for msg in t.messages:
                lines.append(f"  [{msg.author}]: {msg.text}")
            if not approved:
                lines.append(f"  To reply: revspec reply {spec_path} {tid} \"<your reply>\"")
            lines.append("")

    if not approved and (new_ids or reply_ids):
        lines.append(f"When done replying, run: revspec watch {spec_path}")
        lines.append("")

    return "\n".join(lines)


def _format_submit_output(resolved_threads, spec_path):
    lines = ["=== Submit: Rewrite Requested ===", ""]
    if resolved_threads:
        lines.append("Resolved threads:")
        for t in resolved_threads:
            reviewer_msgs = [m for m in t.messages if m.author == "reviewer"]
            owner_msgs = [m for m in t.messages if m.author == "owner"]
            lines.append(f"  {t.id} (line {t.line}): \"{'; '.join(m.text for m in reviewer_msgs)}\"")
            if owner_msgs:
                lines.append(f"    \u2192 AI: \"{'; '.join(m.text for m in owner_msgs)}\"")
        lines.append("")
    lines.append(f"Rewrite the spec incorporating the above in a single atomic write (one Write tool call), then run: revspec watch {spec_path}")
    lines.append("")
    return "\n".join(lines)


def _format_approve_output(batch_events, spec_lines, spec_path, all_events=None):
    """Format approve output, surfacing any unprocessed comments.

    batch_events: events from the current offset (used to find actionable items).
    all_events: full event history (used to replay threads). Falls back to batch_events.
    """
    actionable = [e for e in batch_events if e.type in ("comment", "reply") and e.author == "reviewer"]
    output = ""
    if actionable:
        thread_source = all_events if all_events is not None else batch_events
        all_threads = replay_events_to_threads(thread_source)
        threads_by_id = {t.id: t for t in all_threads}
        output = _format_watch_output(actionable, threads_by_id, spec_lines, spec_path, approved=True)
    output += "Review approved.\n"
    return output


def _get_context(spec_lines, line_number, context_size):
    idx = line_number - 1
    start = max(0, idx - context_size)
    end = min(len(spec_lines) - 1, idx + context_size)
    return [
        f"{'>' if i == idx else ' '} {i + 1}: {spec_lines[i]}"
        for i in range(start, end + 1)
    ]


def _find_current_round_start(events):
    count = 0
    for i in range(len(events) - 1, -1, -1):
        if events[i].type == "submit":
            count += 1
            if count == 2:
                return i + 1
    return 0


def _find_last_index(lst, pred):
    for i in range(len(lst) - 1, -1, -1):
        if pred(lst[i]):
            return i
    return -1


def _acquire_lock(lock_path):
    for attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            if attempt > 0:
                print("Error: Could not acquire lock", file=sys.stderr)
                sys.exit(3)
            # Check existing lock for staleness
            try:
                locked_pid = int(lock_path.read_text().strip())
            except (ValueError, OSError):
                lock_path.unlink(missing_ok=True)
                continue  # retry
            if locked_pid == os.getpid():
                return  # We already hold it
            try:
                os.kill(locked_pid, 0)
                print(f"Error: Another revspec watch is running (PID {locked_pid})", file=sys.stderr)
                sys.exit(3)
            except OSError:
                lock_path.unlink(missing_ok=True)
                continue  # stale lock, retry


def _release_lock(lock_path):
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_offset(offset_path):
    if not offset_path.exists():
        return 0, 0
    lines = offset_path.read_text().strip().split("\n")
    try:
        offset = int(lines[0]) if lines else 0
    except ValueError:
        offset = 0
    try:
        submit_ts = int(lines[1]) if len(lines) > 1 else 0
    except ValueError:
        submit_ts = 0
    return offset, submit_ts


def _write_offset(offset_path, offset, submit_ts=0):
    tmp = str(offset_path) + ".tmp"
    content = f"{offset}\n{submit_ts}" if submit_ts else str(offset)
    Path(tmp).write_text(content)
    os.replace(tmp, str(offset_path))


def _cleanup(lock_path, offset_path):
    for p in (lock_path, offset_path):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
