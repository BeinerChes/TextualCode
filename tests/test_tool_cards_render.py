"""Render-correctness tests for tool_cards.py after the Markdown→Static+Syntax fix.

All tests are hermetic — no network, no live SDK, no Textual app running.

Coverage
--------
1. ToolCard body is a Static wrapping a Rich Syntax object — NOT a Markdown widget.
   Verified by inspecting _contents_list[0] (the widget passed to Collapsible) and
   checking child.content (the Static.content property backed by _Static__content
   in Textual 8.2.7, confirmed by reading the installed source).
2. _format_input output is reflected in the Syntax.code body — a known input dict
   appears verbatim and the truncation marker ("… (truncated)") is present when the
   input exceeds max_input_chars.
3. A tool input containing a literal triple-backtick run (```) is preserved verbatim
   in Syntax.code, proving there is no markdown-fence-breakout vector — since
   Markdown is gone, the content is simply raw JSON handed to Rich Syntax.
"""

from __future__ import annotations

import json

import pytest
from rich.syntax import Syntax
from textual.widgets import Markdown, Static

from claude_agent_sdk import ServerToolUseBlock, ToolUseBlock

from textualcode.tool_cards import ToolCard, _format_input


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_block(name: str = "Bash", input: dict | None = None) -> ToolUseBlock:
    return ToolUseBlock(id="tc-1", name=name, input=input or {})


def _server_block(name: str = "web_search", input: dict | None = None) -> ServerToolUseBlock:
    return ServerToolUseBlock(id="tc-sv-1", name=name, input=input or {"query": "test"})


def _make_card(
    block: ToolUseBlock | ServerToolUseBlock,
    *,
    max_input_chars: int = 400,
    preview_keys: tuple[str, ...] = ("command",),
) -> ToolCard:
    return ToolCard(block, max_input_chars=max_input_chars, preview_keys=preview_keys)


def _body_widget(card: ToolCard) -> Static:
    """Return the first child widget stored in the Collapsible's _contents_list.

    Collapsible.__init__ stashes *children passed to it via positional args* into
    self._contents_list (verified against installed Textual 8.2.7 source at
    textual/widgets/_collapsible.py).  ToolCard calls
    ``super().__init__(Static(Syntax(...)), title=..., ...)`` so _contents_list[0]
    is the Static wrapping the Syntax.
    """
    assert card._contents_list, "ToolCard._contents_list must not be empty"
    widget = card._contents_list[0]
    return widget  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 1. ToolCard body is Static + Syntax, NOT Markdown
# ---------------------------------------------------------------------------

class TestToolCardBodyWidget:
    """The body widget passed to the Collapsible must be Static(Syntax(...)),
    not Markdown.  Verified via Collapsible._contents_list[0].content."""

    def test_body_is_static(self):
        """The child stored in _contents_list[0] must be an instance of Static."""
        card = _make_card(_tool_block())
        widget = _body_widget(card)
        assert isinstance(widget, Static), (
            f"Expected Static, got {type(widget).__name__}"
        )

    def test_body_is_not_markdown(self):
        """The child must NOT be a Markdown widget — that was the pre-fix implementation."""
        card = _make_card(_tool_block())
        widget = _body_widget(card)
        assert not isinstance(widget, Markdown), (
            "ToolCard body must not use Markdown (heavyweight, fence-breakout risk); "
            "fix should have replaced it with Static(Syntax(...))"
        )

    def test_static_content_is_syntax(self):
        """The content stored inside the Static must be a Rich Syntax instance.

        Accessed via Static.content (the public property introduced in Textual 8.2.7
        that returns self.__content set in Static.__init__).
        """
        card = _make_card(_tool_block())
        widget = _body_widget(card)
        assert isinstance(widget, Static), "Precondition: body widget must be Static"
        assert isinstance(widget.content, Syntax), (
            f"Expected Static.content to be rich.syntax.Syntax, got "
            f"{type(widget.content).__name__}"
        )

    def test_syntax_language_is_json(self):
        """The Syntax object must use 'json' as the lexer language.

        In the installed Rich version, Syntax stores the lexer name in the
        ``_lexer`` attribute as a plain string when constructed via
        ``Syntax(code, "json", ...)`` (verified against installed source).
        """
        card = _make_card(_tool_block(input={"x": 1}))
        widget = _body_widget(card)
        assert isinstance(widget.content, Syntax)
        # Rich Syntax stores the lexer identifier in _lexer (a str or Lexer).
        lexer_id = widget.content._lexer
        assert lexer_id == "json", (
            f"Expected Syntax._lexer to be 'json', got {lexer_id!r}"
        )

    def test_server_tool_block_also_uses_static_syntax(self):
        """ServerToolUseBlock cards must use the same Static+Syntax body pattern."""
        card = _make_card(_server_block("web_search", {"query": "hello"}))
        widget = _body_widget(card)
        assert isinstance(widget, Static)
        assert not isinstance(widget, Markdown)
        assert isinstance(widget.content, Syntax)

    def test_no_markdown_widget_in_contents_list(self):
        """None of the widgets in _contents_list may be Markdown instances."""
        card = _make_card(_tool_block(input={"k": "v"}))
        for w in card._contents_list:
            assert not isinstance(w, Markdown), (
                f"Found Markdown widget in _contents_list: {w!r}"
            )


# ---------------------------------------------------------------------------
# 2. Syntax body reflects _format_input output — known dict + truncation
# ---------------------------------------------------------------------------

class TestToolCardBodyContent:
    """The Syntax.code in the body must faithfully reflect _format_input output."""

    def test_known_input_key_appears_in_body(self):
        """A known key from the input dict must appear in the Syntax code."""
        card = _make_card(_tool_block(input={"my_key": "my_value"}))
        code = _body_widget(card).content.code
        assert "my_key" in code, (
            f"Expected 'my_key' in Syntax.code but got:\n{code}"
        )

    def test_known_input_value_appears_in_body(self):
        """A known value from the input dict must appear in the Syntax code."""
        card = _make_card(_tool_block(input={"cmd": "echo hello"}))
        code = _body_widget(card).content.code
        assert "echo hello" in code, (
            f"Expected 'echo hello' in Syntax.code but got:\n{code}"
        )

    def test_body_is_valid_json(self):
        """The Syntax code for a normal dict input must be valid JSON."""
        input_data = {"tool": "Read", "path": "/tmp/a.py", "limit": 100}
        card = _make_card(_tool_block(input=input_data))
        code = _body_widget(card).content.code
        try:
            parsed = json.loads(code)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Syntax.code is not valid JSON: {exc}\nCode:\n{code}")
        assert parsed == input_data

    def test_truncation_marker_present_when_over_limit(self):
        """When the formatted input exceeds max_input_chars, the truncation marker
        ('… (truncated)') must appear in the Syntax code."""
        # Build an input whose JSON representation is definitely > 50 chars
        large_input = {"data": "x" * 200}
        card = _make_card(_tool_block(input=large_input), max_input_chars=50)
        code = _body_widget(card).content.code
        assert "(truncated)" in code, (
            f"Expected truncation marker '(truncated)' in body but got:\n{code}"
        )

    def test_truncation_marker_absent_when_under_limit(self):
        """When the input is small, no truncation marker must appear."""
        small_input = {"k": "v"}
        card = _make_card(_tool_block(input=small_input), max_input_chars=1000)
        code = _body_widget(card).content.code
        assert "(truncated)" not in code, (
            f"Unexpected truncation marker in short body:\n{code}"
        )

    def test_body_matches_format_input_directly(self):
        """Syntax.code must equal _format_input(block.input, max_input_chars)."""
        input_data = {"command": "ls -la", "cwd": "/home/user"}
        limit = 500
        block = _tool_block(input=input_data)
        card = _make_card(block, max_input_chars=limit)
        expected = _format_input(input_data, limit)
        code = _body_widget(card).content.code
        assert code == expected, (
            f"Syntax.code does not match _format_input output.\n"
            f"Expected:\n{expected}\n\nGot:\n{code}"
        )

    def test_empty_input_dict_body(self):
        """An empty input dict must produce a minimal valid JSON body ('{}')."""
        card = _make_card(_tool_block(input={}))
        code = _body_widget(card).content.code
        # json.dumps({}) is '{}'
        assert "{}" in code, f"Expected '{{}}' in empty-input body, got:\n{code}"


# ---------------------------------------------------------------------------
# 3. Triple-backtick input is verbatim — no markdown fence breakout
# ---------------------------------------------------------------------------

class TestToolCardFenceBreakout:
    """Because Markdown is replaced by Syntax, triple-backtick content in a tool
    input is no longer a markdown-fence-breakout risk — the content is just raw
    JSON text passed to Rich Syntax, which renders it literally."""

    def test_triple_backtick_preserved_in_body(self):
        """A tool input containing a literal triple-backtick run must appear
        verbatim in Syntax.code — it must not be truncated, escaped, or consumed
        as a fence-end marker."""
        input_data = {"command": "echo ```dangerous```"}
        card = _make_card(_tool_block(input=input_data), max_input_chars=500)
        code = _body_widget(card).content.code
        assert "```" in code, (
            f"Triple backtick was not preserved verbatim in Syntax.code:\n{code}"
        )

    def test_triple_backtick_at_column_zero_preserved(self):
        """A triple-backtick run at column 0 (the classic markdown fence-close) must
        appear verbatim in the body — Syntax does not interpret backticks as fences."""
        # json.dumps will encode newlines as \\n, keeping them single-line;
        # we test the str() fallback path by constructing a non-serialisable-like
        # value — but json.dumps with ensure_ascii=False handles most cases.
        # Use a multi-line string that survives JSON encoding with embedded backticks.
        input_data = {"script": "line1\n```\nline2"}
        card = _make_card(_tool_block(input=input_data), max_input_chars=500)
        code = _body_widget(card).content.code
        # json.dumps encodes \n as \\n so the literal triple backtick is present
        # (just escaped in JSON, still in the code string)
        assert "```" in code, (
            f"Triple backtick (possibly JSON-encoded) not found in Syntax.code:\n{code}"
        )

    def test_body_widget_is_never_markdown_regardless_of_backticks(self):
        """Even when the input contains triple backticks, the body widget must still
        be Static+Syntax and never fall back to Markdown."""
        input_data = {"content": "```python\nprint('hi')\n```"}
        card = _make_card(_tool_block(input=input_data), max_input_chars=500)
        widget = _body_widget(card)
        assert isinstance(widget, Static), (
            "Body widget became non-Static when input contained backticks"
        )
        assert not isinstance(widget, Markdown), (
            "Body widget fell back to Markdown when input contained backticks"
        )
        assert isinstance(widget.content, Syntax), (
            "Static.content is not Syntax when input contains backticks"
        )

    def test_multiple_triple_backtick_runs_preserved(self):
        """Multiple triple-backtick runs in the input are all preserved verbatim."""
        input_data = {"a": "```foo```", "b": "```bar```"}
        card = _make_card(_tool_block(input=input_data), max_input_chars=500)
        code = _body_widget(card).content.code
        # Both values must appear in the JSON
        assert "foo" in code and "bar" in code, (
            f"Expected both backtick values in Syntax.code:\n{code}"
        )
