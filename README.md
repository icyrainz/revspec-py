# revspec (Python)

A terminal-based spec review tool with real-time AI conversation. Python implementation of [revspec](https://github.com/icyrainz/revspec).

This is a pure-Python alternative for environments where the original Bun-based executable is unavailable. Both versions share the same JSONL protocol and are fully interchangeable.

## Install

```bash
pipx install revspec
```

Or with pip:

```bash
pip install revspec
```

Requires Python 3.11+.

## Usage

```bash
# Interactive review
revspec spec.md

# AI integration (used by the /revspec Claude Code skill)
revspec watch spec.md
revspec reply spec.md <threadId> "<text>"
```

## Claude Code integration

See the [original revspec repo](https://github.com/icyrainz/revspec) for the `/revspec` skill and Claude Code setup instructions. The skill works with either the Bun or Python version — whichever `revspec` is on your PATH.
