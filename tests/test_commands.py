"""Tests for commands.py — pure command parsing."""

from revspec.commands import parse_command, CommandResult


class TestForceQuit:
    def test_q_bang(self):
        assert parse_command("q!").action == "force_quit"

    def test_qa_bang(self):
        assert parse_command("qa!").action == "force_quit"

    def test_wq_bang(self):
        assert parse_command("wq!").action == "force_quit"

    def test_wqa_bang(self):
        assert parse_command("wqa!").action == "force_quit"

    def test_qw_bang(self):
        assert parse_command("qw!").action == "force_quit"

    def test_qwa_bang(self):
        assert parse_command("qwa!").action == "force_quit"


class TestSafeQuit:
    def test_q(self):
        assert parse_command("q").action == "quit"

    def test_qa(self):
        assert parse_command("qa").action == "quit"

    def test_wq(self):
        assert parse_command("wq").action == "quit"

    def test_wqa(self):
        assert parse_command("wqa").action == "quit"

    def test_qw(self):
        assert parse_command("qw").action == "quit"

    def test_qwa(self):
        assert parse_command("qwa").action == "quit"


class TestNamedCommands:
    def test_submit(self):
        assert parse_command("submit").action == "submit"

    def test_approve(self):
        assert parse_command("approve").action == "approve"

    def test_help(self):
        assert parse_command("help").action == "help"

    def test_resolve(self):
        assert parse_command("resolve").action == "resolve"

    def test_reload(self):
        assert parse_command("reload").action == "reload"

    def test_wrap(self):
        assert parse_command("wrap").action == "wrap"


class TestGotoLine:
    def test_positive_number(self):
        r = parse_command("42")
        assert r.action == "goto"
        assert r.args["line"] == 42

    def test_line_1(self):
        r = parse_command("1")
        assert r.action == "goto"
        assert r.args["line"] == 1

    def test_large_number(self):
        r = parse_command("9999")
        assert r.action == "goto"
        assert r.args["line"] == 9999

    def test_zero_is_unknown(self):
        assert parse_command("0").action == "unknown"

    def test_negative_is_unknown(self):
        assert parse_command("-1").action == "unknown"


class TestUnknown:
    def test_garbage(self):
        r = parse_command("foobar")
        assert r.action == "unknown"
        assert r.args["raw"] == "foobar"

    def test_empty(self):
        r = parse_command("")
        assert r.action == "unknown"

    def test_whitespace_stripped(self):
        assert parse_command("  q  ").action == "quit"

    def test_partial_command(self):
        assert parse_command("sub").action == "unknown"
