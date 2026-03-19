"""Tests for renderer.py — pure rendering functions."""

from rich.text import Text
from rich.style import Style

from revspec.renderer import (
    line_style, is_block_element, append_line_content,
    append_inline_styled, apply_search_highlight, smartcase_prepare,
    gutter_width, HIGHLIGHT_STYLE,
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

    def test_no_cursor_has_crust_bg(self):
        from revspec.theme import THEME
        s = line_style("hello", False, False)
        assert s.bgcolor is not None
        assert s.bgcolor.name == THEME["crust"]


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


class TestSmartcasePrepare:
    def test_lowercase_query_is_insensitive(self):
        q, cs = smartcase_prepare("hello")
        assert q == "hello"
        assert cs is False

    def test_uppercase_query_is_sensitive(self):
        q, cs = smartcase_prepare("Hello")
        assert q == "Hello"
        assert cs is True

    def test_all_caps_is_sensitive(self):
        q, cs = smartcase_prepare("FOO")
        assert q == "FOO"
        assert cs is True

    def test_digits_only_is_insensitive(self):
        q, cs = smartcase_prepare("123")
        assert q == "123"
        assert cs is False


class TestApplySearchHighlight:
    def _make_text(self, gutter: str, content: str) -> Text:
        text = Text()
        text.append(gutter, Style(color="white"))
        text.append(content, Style(color="white"))
        return text

    def test_basic_highlight(self):
        text = self._make_text(">>", "hello world hello")
        apply_search_highlight(text, 2, "hello")
        assert text.plain == ">>hello world hello"
        # Check that highlight style is applied at correct positions
        spans = text._spans
        highlight_spans = [s for s in spans if s.style == HIGHLIGHT_STYLE]
        assert len(highlight_spans) == 2
        assert highlight_spans[0].start == 2  # gutter(2) + 0
        assert highlight_spans[0].end == 7    # gutter(2) + 5
        assert highlight_spans[1].start == 14 # gutter(2) + 12
        assert highlight_spans[1].end == 19   # gutter(2) + 17

    def test_case_insensitive(self):
        text = self._make_text(">>", "Hello World")
        apply_search_highlight(text, 2, "hello")
        highlight_spans = [s for s in text._spans if s.style == HIGHLIGHT_STYLE]
        assert len(highlight_spans) == 1
        assert text.plain[highlight_spans[0].start:highlight_spans[0].end] == "Hello"

    def test_case_sensitive(self):
        text = self._make_text(">>", "Hello hello")
        apply_search_highlight(text, 2, "Hello")
        highlight_spans = [s for s in text._spans if s.style == HIGHLIGHT_STYLE]
        assert len(highlight_spans) == 1
        assert text.plain[highlight_spans[0].start:highlight_spans[0].end] == "Hello"

    def test_no_match(self):
        text = self._make_text(">>", "hello world")
        apply_search_highlight(text, 2, "xyz")
        highlight_spans = [s for s in text._spans if s.style == HIGHLIGHT_STYLE]
        assert len(highlight_spans) == 0

    def test_empty_query_noop(self):
        text = self._make_text(">>", "hello world")
        apply_search_highlight(text, 2, "")
        highlight_spans = [s for s in text._spans if s.style == HIGHLIGHT_STYLE]
        assert len(highlight_spans) == 0

    def test_gutter_not_highlighted(self):
        # "he" appears in gutter ">>he" but should not be highlighted
        text = self._make_text(">>he", "llo world hello")
        apply_search_highlight(text, 4, "he")
        highlight_spans = [s for s in text._spans if s.style == HIGHLIGHT_STYLE]
        # Only matches in content, not gutter
        for span in highlight_spans:
            assert span.start >= 4


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
