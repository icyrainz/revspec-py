"""Fake AI reply for VHS demo — replies to comments and rewrites spec on submit."""

import json
import os
import time
from pathlib import Path

SPEC = Path("demo/spec.md")
JSONL = Path("demo/spec.review.jsonl")
LOCK = Path("demo/spec.review.lock")

REPLIES = {
    1: (
        "Good catch! You're right \u2014 5 attempts per 15 min is too strict. "
        "I'll bump it to **10 attempts per 15 min** with progressive backoff. "
        "This protects against brute force while being forgiving of typos."
    ),
    2: (
        "Great question. Yes, combining passkey with OAuth is possible via "
        "WebAuthn's `allowCredentials` list. I'll add a hybrid flow in Phase 2 "
        "that lets enterprise users link both methods to one account."
    ),
}

# Create lock file so the TUI thinks a watcher is running
LOCK.write_text(str(os.getpid()))

seen_comments = set()
replied_count = 0
submitted = False

try:
    while not submitted:
        time.sleep(0.5)
        if not JSONL.exists():
            continue

        for line in JSONL.read_text().splitlines():
            try:
                ev = json.loads(line)
            except (json.JSONDecodeError, KeyError):
                continue

            # Reply to new comments
            if ev.get("type") == "comment":
                tid = ev["threadId"]
                if tid not in seen_comments:
                    seen_comments.add(tid)
                    replied_count += 1
                    if replied_count in REPLIES:
                        time.sleep(3)
                        reply = {
                            "type": "reply",
                            "threadId": tid,
                            "author": "owner",
                            "text": REPLIES[replied_count],
                            "ts": int(time.time() * 1000),
                        }
                        with open(JSONL, "a") as f:
                            f.write(json.dumps(reply) + "\n")

            # On submit, rewrite the spec
            if ev.get("type") == "submit":
                submitted = True

    # Wait a moment then rewrite the spec
    time.sleep(2)
    content = SPEC.read_text()
    # Apply the rate limit change from comment 1
    content = content.replace(
        "| `/auth/login` | 5 attempts | 15 min | Lock account + notify |",
        "| `/auth/login` | 10 attempts | 15 min | Progressive backoff (1m/5m/15m) |",
    )
    # Apply the passkey+OAuth change from comment 2
    content = content.replace(
        "3. Fallback: allow password login if passkey fails",
        "3. Fallback: allow password login if passkey fails\n"
        "4. Hybrid flow: link passkey + OAuth credentials to single account",
    )
    SPEC.write_text(content)

finally:
    LOCK.unlink(missing_ok=True)
