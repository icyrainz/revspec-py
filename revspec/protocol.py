"""JSONL live event protocol — compatible with the TypeScript implementation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

EventType = Literal[
    "comment", "reply", "resolve", "unresolve",
    "approve", "delete", "round", "session-end", "submit",
]

VALID_EVENT_TYPES = {
    "comment", "reply", "resolve", "unresolve",
    "approve", "delete", "round", "session-end", "submit",
}


@dataclass
class LiveEvent:
    type: EventType
    author: str
    ts: int
    thread_id: str | None = None
    line: int | None = None
    text: str | None = None
    round: int | None = None


def is_valid_event(obj: dict) -> bool:
    if obj.get("type") not in VALID_EVENT_TYPES:
        return False
    if not isinstance(obj.get("ts"), (int, float)):
        return False
    if not isinstance(obj.get("author"), str):
        return False
    t = obj["type"]
    if t not in ("approve", "round", "session-end", "submit"):
        if not isinstance(obj.get("threadId"), str):
            return False
    if t == "reply" and not isinstance(obj.get("text"), str):
        return False
    if t == "comment":
        if not isinstance(obj.get("text"), str):
            return False
        if not isinstance(obj.get("line"), (int, float)):
            return False
    if t == "round" and not isinstance(obj.get("round"), (int, float)):
        return False
    return True


def parse_event(obj: dict) -> LiveEvent:
    return LiveEvent(
        type=obj["type"],
        author=obj["author"],
        ts=int(obj["ts"]),
        thread_id=obj.get("threadId"),
        line=int(obj["line"]) if obj.get("line") is not None else None,
        text=obj.get("text"),
        round=int(obj["round"]) if obj.get("round") is not None else None,
    )


def append_event(jsonl_path: str, event: LiveEvent) -> None:
    data: dict = {"type": event.type, "author": event.author, "ts": event.ts}
    if event.thread_id is not None:
        data["threadId"] = event.thread_id
    if event.line is not None:
        data["line"] = event.line
    if event.text is not None:
        data["text"] = event.text
    if event.round is not None:
        data["round"] = event.round
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")


def read_events(jsonl_path: str, offset: int = 0) -> tuple[list[LiveEvent], int]:
    if not os.path.exists(jsonl_path):
        return [], 0
    with open(jsonl_path, "rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        if file_size <= offset:
            return [], offset
        f.seek(offset)
        # Mid-line alignment safety: if offset lands mid-line, skip to next newline
        if offset > 0:
            prev_byte = b""
            f.seek(offset - 1)
            prev_byte = f.read(1)
            if prev_byte != b"\n":
                f.readline()  # skip partial line
        else:
            f.seek(offset)
        raw = f.read().decode("utf-8")

    events: list[LiveEvent] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if is_valid_event(obj):
                events.append(parse_event(obj))
        except (json.JSONDecodeError, KeyError):
            pass
    return events, file_size


@dataclass
class Thread:
    id: str
    line: int
    status: Literal["open", "pending", "resolved", "outdated"]
    messages: list[Message] = field(default_factory=list)


@dataclass
class Message:
    author: Literal["reviewer", "owner"]
    text: str
    ts: int | None = None


def replay_events_to_threads(events: list[LiveEvent]) -> list[Thread]:
    threads: dict[str, Thread] = {}
    order: list[str] = []

    for ev in events:
        if ev.type == "comment":
            if not ev.thread_id or ev.line is None or not ev.text:
                continue
            t = Thread(
                id=ev.thread_id,
                line=ev.line,
                status="open",
                messages=[Message(author="reviewer", text=ev.text, ts=ev.ts)],
            )
            threads[ev.thread_id] = t
            order.append(ev.thread_id)

        elif ev.type == "reply":
            if not ev.thread_id or not ev.text:
                continue
            t = threads.get(ev.thread_id)
            if not t:
                continue
            t.messages.append(Message(
                author=ev.author if ev.author in ("reviewer", "owner") else "reviewer",
                text=ev.text,
                ts=ev.ts,
            ))
            t.status = "pending" if ev.author == "owner" else "open"

        elif ev.type == "resolve":
            if ev.thread_id and ev.thread_id in threads:
                threads[ev.thread_id].status = "resolved"

        elif ev.type == "unresolve":
            if ev.thread_id and ev.thread_id in threads:
                threads[ev.thread_id].status = "open"

        elif ev.type == "delete":
            if ev.thread_id:
                threads.pop(ev.thread_id, None)

    return [threads[tid] for tid in order if tid in threads and threads[tid].messages]
