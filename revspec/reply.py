"""revspec reply — CLI subcommand for AI to reply to threads."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .protocol import LiveEvent, append_event, read_events, replay_events_to_threads


def run_reply(spec_file: str, thread_id: str, text: str) -> None:
    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    if not text or not text.strip():
        print("Error: Reply text cannot be empty", file=sys.stderr)
        sys.exit(1)

    jsonl_path = str(spec_path.parent / (spec_path.stem + ".review.jsonl"))
    if not Path(jsonl_path).exists():
        print(f"Error: JSONL file not found: {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    # Validate thread ID exists and is not deleted
    events, _ = read_events(jsonl_path)
    threads = replay_events_to_threads(events)
    if not any(t.id == thread_id for t in threads):
        print(f"Error: Thread ID not found: {thread_id}", file=sys.stderr)
        sys.exit(1)

    # Clean shell escaping artifacts
    clean_text = text.replace("\\!", "!")

    append_event(jsonl_path, LiveEvent(
        type="reply", thread_id=thread_id,
        author="owner", text=clean_text,
        ts=int(time.time() * 1000),
    ))
