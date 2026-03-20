"""Key sequence registry and routing — pure logic, no Textual dependency."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeySequence:
    """A two-key sequence entry."""

    seq_key: str  # internal key, e.g. "right_square_brackett"
    display: str  # display hint, e.g. "]t"
    label: str  # hint label, e.g. "thread"
    handler_name: str  # method name on RevspecApp, e.g. "_seq_next_thread"


# All two-key sequences. This is the single source of truth.
SEQUENCE_REGISTRY: list[KeySequence] = [
    # ] prefix
    KeySequence("right_square_brackett", "]t", "thread", "_seq_next_thread"),
    KeySequence("right_square_bracketr", "]r", "unread", "_seq_next_unread"),
    KeySequence("right_square_bracket1", "]1", "h1", "_seq_heading_1_fwd"),
    KeySequence("right_square_bracket2", "]2", "h2", "_seq_heading_2_fwd"),
    KeySequence("right_square_bracket3", "]3", "h3", "_seq_heading_3_fwd"),
    KeySequence("right_square_bracketd", "]d", "diff→", "_next_hunk"),
    # [ prefix
    KeySequence("left_square_brackett", "[t", "thread", "_seq_prev_thread"),
    KeySequence("left_square_bracketr", "[r", "unread", "_seq_prev_unread"),
    KeySequence("left_square_bracket1", "[1", "h1", "_seq_heading_1_back"),
    KeySequence("left_square_bracket2", "[2", "h2", "_seq_heading_2_back"),
    KeySequence("left_square_bracket3", "[3", "h3", "_seq_heading_3_back"),
    KeySequence("left_square_bracketd", "[d", "←diff", "_prev_hunk"),
    # g prefix
    KeySequence("gg", "gg", "top", "_seq_go_top"),
    # z prefix
    KeySequence("zz", "zz", "center", "_seq_center"),
    # d prefix
    KeySequence("dd", "dd", "delete", "_delete_thread"),
    # ' prefix
    KeySequence("apostropheapostrophe", "''", "swap", "_jump_swap"),
    # \ prefix
    KeySequence("backslashw", "\\w", "wrap", "_toggle_wrap"),
    KeySequence("backslashn", "\\n", "lines", "_toggle_line_numbers"),
    KeySequence("backslashd", "\\d", "diff", "_toggle_diff"),
]

# Known prefix names for deriving prefix → hint mappings
_PREFIX_NAMES = (
    "right_square_bracket",
    "left_square_bracket",
    "apostrophe",
    "backslash",
    "g",
    "z",
    "d",
)


class SequenceRouter:
    """Resolves two-key sequences and generates hint text.

    Built from the SEQUENCE_REGISTRY at init time.
    """

    def __init__(self, registry: list[KeySequence] | None = None) -> None:
        if registry is None:
            registry = SEQUENCE_REGISTRY
        self._handlers: dict[str, str] = {}
        self._prefix_hints: dict[str, list[tuple[str, str]]] = {}
        self._prefixes: set[str] = set()

        for entry in registry:
            self._handlers[entry.seq_key] = entry.handler_name
            for pname in _PREFIX_NAMES:
                if entry.seq_key.startswith(pname) and len(entry.seq_key) > len(pname):
                    self._prefixes.add(pname)
                    self._prefix_hints.setdefault(pname, []).append(
                        (entry.display, entry.label)
                    )
                    break

    def is_prefix(self, key: str) -> bool:
        """Check if key is the start of a two-key sequence."""
        return key in self._prefixes

    def resolve(self, prefix: str, key: str) -> str | None:
        """Resolve prefix + key into a handler name, or None."""
        return self._handlers.get(prefix + key)

    def hints_for_prefix(self, prefix: str) -> list[tuple[str, str]]:
        """Return [(display, label), ...] for a given prefix key."""
        return self._prefix_hints.get(prefix, [])

    @property
    def prefixes(self) -> set[str]:
        return self._prefixes
