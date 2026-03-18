"""Tests for renderer.py — pure rendering functions."""

from rich.text import Text
from rich.style import Style

from revspec.renderer import (
    line_style, is_block_element, append_line_content,
    append_inline_styled, append_highlighted, gutter_width,
)
from revspec.theme import THEME


class TestLineStyle:
    def test_h1_heading(self):
        s = line_style("# Title", False, False)
        assert s.color and s.color.name == THEME["blue"]
        assert s.bold

    def test_h2_heading(self):
        s = line_style("## Section", False, False)
        assert s.color and s.color.name == THEME["blue"]

    def test_h3_heading(self):
        s = line_style("### Sub", False, False)
        assert s.color and s.color.name == THEME["mauve"]

    def test_code_fence(self):
        s = line_style("```python", False, False)
        assert s.color and s.color.name == THEME["text_dim"]

    def test_inside_code_block(self):
        s = line_style("some code", True, False)
        assert s.color and s.color.name == THEME["green"]

    def test_regular_text(self):
        s = line_style("hello world", False, False)
        assert s.color and s.color.name == THEME["text"]

    def test_cursor_has_panel_bg(self):
        s = line_style("hello", False, True)
        assert s.bgcolor is not None

    def test_no_cursor_no_bg(self):
        s = line_style("hello", False, False)
        assert s.bgcolor is None


class TestIsBlockElement:
    def test_blockquote(self):
        assert is_block_element("> quote", False)

    def test_list_dash(self):
        assert is_block_element("- item", False)

    def test_list_asterisk(self):
        assert is_block_element("* item", False)

    def test_hr_dashes(self):
        assert is_block_element("---", False)

    def test_hr_stars(self):
        assert is_block_element("***", False)

    def test_regular_text(self):
        assert not is_block_element("hello", False)

    def test_in_code_block(self):
        assert not is_block_element("> quote", True)

    def test_fence_line(self):
        assert not is_block_element("```", False)


class TestAppendLineContent:
    def test_blockquote(self):
        text = Text()
        append_line_content(text, "> hello", False, False)
        assert "\u2502" in text.plain
        assert "hello" in text.plain

    def test_list_item(self):
        text = Text()
        append_line_content(text, "- item text", False, False)
        assert "\u2022" in text.plain
        assert "item text" in text.plain

    def test_horizontal_rule(self):
        text = Text()
        append_line_content(text, "---", False, False)
        assert "\u2500" in text.plain

    def test_regular_line(self):
        text = Text()
        append_line_content(text, "just text", False, False)
        assert text.plain == "just text"

    def test_empty_line(self):
        text = Text()
        append_line_content(text, "", False, False)
        assert text.plain == " "


class TestAppendInlineStyled:
    def test_plain_text(self):
        text = Text()
        base = Style(color="white")
        append_inline_styled(text, "hello", base)
        assert text.plain == "hello"

    def test_bold(self):
        text = Text()
        base = Style(color="white")
        append_inline_styled(text, "**bold**", base)
        assert "bold" in text.plain

    def test_code(self):
        text = Text()
        base = Style(color="white")
        append_inline_styled(text, "`code`", base)
        assert "code" in text.plain


class TestAppendHighlighted:
    def test_basic_highlight(self):
        text = Text()
        base = Style(color="white")
        append_highlighted(text, "hello world hello", "hello", base)
        plain = text.plain
        assert plain == "hello world hello"

    def test_case_insensitive(self):
        text = Text()
        base = Style(color="white")
        append_highlighted(text, "Hello World", "hello", base)
        assert text.plain == "Hello World"

    def test_case_sensitive(self):
        text = Text()
        base = Style(color="white")
        append_highlighted(text, "Hello hello", "Hello", base)
        assert text.plain == "Hello hello"

    def test_no_match(self):
        text = Text()
        base = Style(color="white")
        append_highlighted(text, "hello world", "xyz", base)
        assert text.plain == "hello world"


class TestGutterWidth:
    def test_with_line_numbers(self):
        num_w, total = gutter_width(100, True)
        assert num_w == 3
        assert total == 2 + 3 + 2  # prefix + num + space

    def test_without_line_numbers(self):
        num_w, total = gutter_width(100, False)
        assert num_w == 0
        assert total == 3

    def test_large_line_count(self):
        num_w, total = gutter_width(10000, True)
        assert num_w == 5
        assert total == 2 + 5 + 2
