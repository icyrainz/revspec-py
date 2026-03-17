"""Tests for markdown table parsing and rendering helpers."""
from revspec.markdown import (
    display_width, parse_table_cells, scan_table_blocks,
    collect_table, count_extra_visual_lines, SEPARATOR_RE,
    _word_wrap_count, parse_inline_markdown,
)


class TestDisplayWidth:
    def test_plain_text(self):
        assert display_width("hello") == 5

    def test_bold(self):
        assert display_width("**bold**") == 4

    def test_italic(self):
        assert display_width("*italic*") == 6

    def test_bold_italic(self):
        assert display_width("***both***") == 4

    def test_inline_code(self):
        assert display_width("`code`") == 4

    def test_link(self):
        assert display_width("[text](http://example.com)") == 4

    def test_strikethrough(self):
        assert display_width("~~struck~~") == 6

    def test_underscore_bold(self):
        assert display_width("__bold__") == 4

    def test_mixed(self):
        assert display_width("plain **bold** `code`") == len("plain bold code")


class TestParseTableCells:
    def test_basic_row(self):
        assert parse_table_cells("| A | B | C |") == ["A", "B", "C"]

    def test_no_trailing_pipe(self):
        assert parse_table_cells("| A | B | C") == ["A", "B", "C"]

    def test_whitespace_trimmed(self):
        assert parse_table_cells("|  foo  |  bar  |") == ["foo", "bar"]

    def test_single_cell(self):
        assert parse_table_cells("| only |") == ["only"]


class TestSeparatorRegex:
    def test_matches_basic(self):
        assert SEPARATOR_RE.match("| --- | --- |")

    def test_matches_colons(self):
        assert SEPARATOR_RE.match("| :---: | ---: |")

    def test_no_match_data_row(self):
        assert not SEPARATOR_RE.match("| A | B |")


class TestCollectTable:
    def test_collects_simple_table(self):
        lines = [
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "| 3 | 4 |",
            "",
            "Not a table",
        ]
        block = collect_table(lines, 0)
        assert len(block.lines) == 4
        assert block.separator_index == 1
        assert len(block.col_widths) == 2

    def test_col_widths_from_content(self):
        lines = [
            "| Name | Description |",
            "| --- | --- |",
            "| A | Short |",
            "| Longer | Much longer text |",
        ]
        block = collect_table(lines, 0)
        assert block.col_widths[0] >= len("Longer")
        assert block.col_widths[1] >= len("Much longer text")


class TestScanTableBlocks:
    def test_finds_table(self):
        lines = [
            "# Title",
            "",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
            "Done",
        ]
        blocks = scan_table_blocks(lines)
        assert 2 in blocks
        assert 3 in blocks
        assert 4 in blocks
        assert 0 not in blocks

    def test_skips_table_in_code_block(self):
        lines = [
            "```",
            "| A | B |",
            "| --- | --- |",
            "```",
        ]
        blocks = scan_table_blocks(lines)
        assert len(blocks) == 0

    def test_multiple_tables(self):
        lines = [
            "| A | B |",
            "| --- | --- |",
            "",
            "| X | Y |",
            "| --- | --- |",
        ]
        blocks = scan_table_blocks(lines)
        assert 0 in blocks
        assert 1 in blocks
        assert 3 in blocks
        assert 4 in blocks


class TestWordWrapCount:
    def test_no_wrap_needed(self):
        assert _word_wrap_count("short", 80) == 0

    def test_single_wrap(self):
        assert _word_wrap_count("a " * 50, 80) == 1

    def test_exact_width_no_wrap(self):
        assert _word_wrap_count("x" * 80, 80) == 0

    def test_one_over_wraps(self):
        assert _word_wrap_count("x" * 81, 80) == 1

    def test_word_break(self):
        # 40 chars + space + 40 chars = 81 total, wraps at space
        text = "a" * 40 + " " + "b" * 40
        assert _word_wrap_count(text, 80) == 1

    def test_zero_width(self):
        assert _word_wrap_count("text", 0) == 0

    def test_empty_string(self):
        assert _word_wrap_count("", 80) == 0

    def test_multiple_wraps(self):
        assert _word_wrap_count("word " * 100, 80) >= 5


class TestCountExtraVisualLines:
    def test_no_tables_no_extra(self):
        lines = ["line 1", "line 2", "line 3"]
        assert count_extra_visual_lines(lines, 2) == 0

    def test_table_adds_borders(self):
        lines = [
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "after table",
        ]
        # Cursor at line 3 (after table) should see top border
        extra = count_extra_visual_lines(lines, 3)
        assert extra >= 1  # at least top border counted

    def test_wrap_adds_lines(self):
        lines = [
            "short",
            "x" * 200,  # long line
            "after",
        ]
        extra = count_extra_visual_lines(lines, 2, wrap_width=80)
        assert extra > 0


class TestParseInlineMarkdown:
    def test_bold(self):
        result = parse_inline_markdown("**hello**")
        assert result == [("hello", {"bold": True})]

    def test_italic(self):
        result = parse_inline_markdown("*hello*")
        assert result == [("hello", {"italic": True})]

    def test_code(self):
        result = parse_inline_markdown("`code`")
        assert result == [("code", {"color": "#cba6f7"})]

    def test_mixed(self):
        result = parse_inline_markdown("plain **bold** text")
        assert result == [
            ("plain ", {}),
            ("bold", {"bold": True}),
            (" text", {}),
        ]

    def test_link(self):
        result = parse_inline_markdown("[click](http://example.com)")
        assert result == [("click", {"color": "#89b4fa", "underline": True})]

    def test_bold_italic(self):
        result = parse_inline_markdown("***both***")
        assert result == [("both", {"bold": True, "italic": True})]

    def test_strikethrough(self):
        result = parse_inline_markdown("~~struck~~")
        assert result == [("struck", {"color": "#6c7086", "strike": True})]

    def test_underscore_bold(self):
        result = parse_inline_markdown("__bold__")
        assert result == [("bold", {"bold": True})]

    def test_underscore_italic(self):
        result = parse_inline_markdown("_italic_")
        assert result == [("italic", {"italic": True})]

    def test_plain_text_passthrough(self):
        result = parse_inline_markdown("no markdown here")
        assert result == [("no markdown here", {})]

    def test_empty_string(self):
        result = parse_inline_markdown("")
        assert result == [("", {})]

    def test_multiple_segments(self):
        result = parse_inline_markdown("a **b** *c* `d`")
        assert len(result) == 6
        assert result[0] == ("a ", {})
        assert result[1] == ("b", {"bold": True})
        assert result[2] == (" ", {})
        assert result[3] == ("c", {"italic": True})
        assert result[4] == (" ", {})
        assert result[5] == ("d", {"color": "#cba6f7"})

    def test_underscore_mid_word_not_matched(self):
        """Underscores inside words should NOT trigger italic/bold."""
        result = parse_inline_markdown("foo_bar_baz")
        assert result == [("foo_bar_baz", {})]
