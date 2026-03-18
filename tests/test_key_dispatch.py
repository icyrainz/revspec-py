"""Tests for key_dispatch.py — sequence registry and router."""

from revspec.key_dispatch import SequenceRouter, KeySequence, SEQUENCE_REGISTRY


class TestSequenceRouterInit:
    def test_default_registry(self):
        router = SequenceRouter()
        assert len(router.prefixes) > 0

    def test_custom_registry(self):
        reg = [KeySequence("gz", "gz", "test", "_handler")]
        router = SequenceRouter(reg)
        assert router.is_prefix("g")
        assert router.resolve("g", "z") == "_handler"

    def test_empty_registry(self):
        router = SequenceRouter([])
        assert len(router.prefixes) == 0


class TestIsPrefix:
    def test_right_bracket(self):
        router = SequenceRouter()
        assert router.is_prefix("right_square_bracket")

    def test_left_bracket(self):
        router = SequenceRouter()
        assert router.is_prefix("left_square_bracket")

    def test_g_prefix(self):
        router = SequenceRouter()
        assert router.is_prefix("g")

    def test_z_prefix(self):
        router = SequenceRouter()
        assert router.is_prefix("z")

    def test_d_prefix(self):
        router = SequenceRouter()
        assert router.is_prefix("d")

    def test_apostrophe_prefix(self):
        router = SequenceRouter()
        assert router.is_prefix("apostrophe")

    def test_backslash_prefix(self):
        router = SequenceRouter()
        assert router.is_prefix("backslash")

    def test_unknown_is_not_prefix(self):
        router = SequenceRouter()
        assert not router.is_prefix("x")
        assert not router.is_prefix("j")


class TestResolve:
    def test_next_thread(self):
        router = SequenceRouter()
        assert router.resolve("right_square_bracket", "t") == "_seq_next_thread"

    def test_prev_thread(self):
        router = SequenceRouter()
        assert router.resolve("left_square_bracket", "t") == "_seq_prev_thread"

    def test_gg(self):
        router = SequenceRouter()
        assert router.resolve("g", "g") == "_seq_go_top"

    def test_zz(self):
        router = SequenceRouter()
        assert router.resolve("z", "z") == "_seq_center"

    def test_dd(self):
        router = SequenceRouter()
        assert router.resolve("d", "d") == "_delete_thread"

    def test_swap(self):
        router = SequenceRouter()
        assert router.resolve("apostrophe", "apostrophe") == "_jump_swap"

    def test_wrap_toggle(self):
        router = SequenceRouter()
        assert router.resolve("backslash", "w") == "_toggle_wrap"

    def test_line_numbers_toggle(self):
        router = SequenceRouter()
        assert router.resolve("backslash", "n") == "_toggle_line_numbers"

    def test_unknown_sequence_returns_none(self):
        router = SequenceRouter()
        assert router.resolve("g", "x") is None
        assert router.resolve("z", "a") is None
        assert router.resolve("x", "y") is None


class TestHintsForPrefix:
    def test_right_bracket_hints(self):
        router = SequenceRouter()
        hints = router.hints_for_prefix("right_square_bracket")
        displays = [h[0] for h in hints]
        assert "]t" in displays
        assert "]r" in displays
        assert "]1" in displays
        assert "]2" in displays
        assert "]3" in displays

    def test_backslash_hints(self):
        router = SequenceRouter()
        hints = router.hints_for_prefix("backslash")
        displays = [h[0] for h in hints]
        assert "\\w" in displays
        assert "\\n" in displays

    def test_unknown_prefix_returns_empty(self):
        router = SequenceRouter()
        assert router.hints_for_prefix("unknown") == []


class TestRegistryCompleteness:
    def test_all_16_entries(self):
        assert len(SEQUENCE_REGISTRY) == 16

    def test_all_entries_have_handler(self):
        for entry in SEQUENCE_REGISTRY:
            assert entry.handler_name.startswith("_")

    def test_no_duplicate_seq_keys(self):
        keys = [e.seq_key for e in SEQUENCE_REGISTRY]
        assert len(keys) == len(set(keys))
