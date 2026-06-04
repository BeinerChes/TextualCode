"""Quality / correctness tests for tool_cards.py.

All tests are hermetic — no network, no live SDK, no Textual app running.

Coverage
--------
1. _summary: truncates at _SUMMARY_NAME_LIMIT (named constant exists and is
   used); names under the cap are untouched; names over the cap get an ellipsis.
2. _format_input: dict -> pretty JSON; truncation adds '(truncated)' past the
   limit; the json.dumps fallback path (non-serialisable object) yields str(data).
3. tool_preview: returns the first matching preview key's first line capped at
   60 chars with an ellipsis; returns '' when no key matches.
4. ToolGroupCard: instantiates with self._contents declared (None before compose).
"""

from __future__ import annotations

import json

import pytest

from claude_agent_sdk import ServerToolUseBlock, ToolUseBlock

import textualcode.tool_cards as tc_module
from textualcode.tool_cards import (
    ToolGroupCard,
    _format_input,
    tool_preview,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_block(name: str = "Bash", input: dict | None = None) -> ToolUseBlock:
    return ToolUseBlock(id="tq-1", name=name, input=input or {})


def _server_block(name: str = "web_search", input: dict | None = None) -> ServerToolUseBlock:
    return ServerToolUseBlock(id="tq-sv-1", name=name, input=input or {"query": "test"})


def _make_group() -> ToolGroupCard:
    return ToolGroupCard(max_input_chars=400, preview_keys=("command",))


# ---------------------------------------------------------------------------
# 1. _summary: named constant + truncation boundary
# ---------------------------------------------------------------------------

class TestSummaryTruncation:
    """_summary() must truncate the joined names string at _SUMMARY_NAME_LIMIT."""

    def test_constant_exists(self):
        """_SUMMARY_NAME_LIMIT must be a module-level named constant in tool_cards."""
        assert hasattr(tc_module, "_SUMMARY_NAME_LIMIT"), (
            "tool_cards._SUMMARY_NAME_LIMIT constant is missing"
        )

    def test_constant_is_integer(self):
        """_SUMMARY_NAME_LIMIT must be an int."""
        assert isinstance(tc_module._SUMMARY_NAME_LIMIT, int), (
            f"_SUMMARY_NAME_LIMIT must be int, got {type(tc_module._SUMMARY_NAME_LIMIT)}"
        )

    def test_under_cap_names_untouched(self):
        """Names whose joined+escaped length is under the cap must appear in full."""
        group = _make_group()
        # Short names well under any reasonable cap
        group._names = ["Read", "Glob"]
        summary = group._summary()
        assert "Read" in summary, f"'Read' missing from summary: {summary!r}"
        assert "Glob" in summary, f"'Glob' missing from summary: {summary!r}"
        assert "…" not in summary, (
            f"Ellipsis must not appear when names are under the cap: {summary!r}"
        )

    def test_over_cap_names_truncated_with_ellipsis(self):
        """Names whose joined length exceeds the cap must be truncated with '…'."""
        limit = tc_module._SUMMARY_NAME_LIMIT
        group = _make_group()
        # Construct names whose joined string is definitely longer than the cap
        # (each plain ASCII name so escape() is a no-op)
        long_name = "A" * (limit + 10)
        group._names = [long_name]
        summary = group._summary()
        assert "…" in summary, (
            f"Ellipsis must appear when names exceed _SUMMARY_NAME_LIMIT={limit}: "
            f"{summary!r}"
        )

    def test_truncated_names_end_at_limit_boundary(self):
        """After truncation the names segment must be exactly _SUMMARY_NAME_LIMIT
        visible characters (including the ellipsis) — verifying the constant is
        actually used as the slice boundary."""
        limit = tc_module._SUMMARY_NAME_LIMIT
        group = _make_group()
        long_name = "B" * (limit * 2)
        group._names = [long_name]
        summary = group._summary()

        # Extract the names portion that follows ' · '
        assert " · " in summary, f"Expected ' · ' separator in summary: {summary!r}"
        names_part = summary.split(" · ", 1)[1]

        # names_part should be exactly limit chars long:
        # limit-1 name chars + 1 ellipsis char = limit chars
        assert len(names_part) == limit, (
            f"names_part length {len(names_part)} != _SUMMARY_NAME_LIMIT={limit}; "
            f"names_part={names_part!r}"
        )
        assert names_part.endswith("…"), (
            f"names_part must end with ellipsis: {names_part!r}"
        )

    def test_constant_used_as_boundary(self):
        """Changing names so their length is exactly at the cap boundary should
        NOT trigger truncation (equal-length names do not exceed the limit)."""
        limit = tc_module._SUMMARY_NAME_LIMIT
        group = _make_group()
        # Build a name whose plain string equals exactly `limit` chars
        exact_name = "C" * limit
        group._names = [exact_name]
        summary = group._summary()
        # The joined names string is exactly `limit` chars; `len(names) > limit`
        # is False so no truncation should occur.
        assert "…" not in summary, (
            f"Ellipsis must NOT appear when joined names length == limit={limit}: "
            f"{summary!r}"
        )

    def test_empty_names_no_ellipsis(self):
        """Zero names -> no names section, no ellipsis."""
        group = _make_group()
        group._names = []
        summary = group._summary()
        assert "…" not in summary, f"No ellipsis expected for empty names: {summary!r}"

    def test_single_name_under_cap(self):
        """A single short name like 'Bash' must appear verbatim."""
        group = _make_group()
        group._names = ["Bash"]
        summary = group._summary()
        assert "Bash" in summary
        assert "…" not in summary

    def test_multiple_names_joined_with_comma_space(self):
        """Multiple names must be joined with ', '."""
        group = _make_group()
        group._names = ["Alpha", "Beta"]
        summary = group._summary()
        assert "Alpha, Beta" in summary, (
            f"Names must be joined with ', ': {summary!r}"
        )


# ---------------------------------------------------------------------------
# 2. _format_input
# ---------------------------------------------------------------------------

class TestFormatInput:
    """_format_input produces pretty JSON, adds truncation marker, falls back to str()."""

    def test_dict_produces_valid_pretty_json(self):
        """A normal dict must produce indented, valid JSON."""
        data = {"tool": "Read", "path": "/tmp/a.py"}
        result = _format_input(data, limit=1000)
        parsed = json.loads(result)
        assert parsed == data, (
            f"_format_input must produce valid JSON matching the input dict; "
            f"got:\n{result}"
        )

    def test_dict_is_pretty_printed(self):
        """Output must be indented (pretty-printed) — not a single-line compact dump."""
        data = {"x": 1, "y": 2}
        result = _format_input(data, limit=1000)
        assert "\n" in result, (
            f"_format_input output must be multi-line (pretty-printed): {result!r}"
        )

    def test_truncation_adds_marker_past_limit(self):
        """When output length exceeds the limit, '(truncated)' must appear."""
        data = {"data": "x" * 300}
        result = _format_input(data, limit=50)
        assert "(truncated)" in result, (
            f"Expected '(truncated)' marker in output past limit, got:\n{result}"
        )

    def test_truncation_cuts_at_limit(self):
        """After truncation the result must not contain all original content."""
        data = {"data": "y" * 300}
        result = _format_input(data, limit=50)
        # The full JSON would be much longer; verify the result is shorter
        full = json.dumps(data, indent=2, ensure_ascii=False)
        assert len(result) < len(full), (
            "Truncated output must be shorter than full JSON"
        )

    def test_no_truncation_marker_when_under_limit(self):
        """When output is within the limit, no truncation marker must appear."""
        data = {"k": "v"}
        result = _format_input(data, limit=1000)
        assert "(truncated)" not in result, (
            f"Unexpected '(truncated)' marker in short output: {result!r}"
        )

    def test_non_serialisable_fallback_to_str(self):
        """When json.dumps raises (non-serialisable object), the result must be
        str(data) (possibly truncated).  The test passes an object that json.dumps
        cannot handle."""

        class _Unserializable:
            def __repr__(self) -> str:
                return "UNSERIALIZABLE_REPR"

        obj = _Unserializable()
        result = _format_input(obj, limit=1000)  # type: ignore[arg-type]
        assert "UNSERIALIZABLE_REPR" in result, (
            f"Fallback path must use str(data); got: {result!r}"
        )

    def test_non_serialisable_fallback_truncated_when_over_limit(self):
        """The str(data) fallback must also respect the limit + add the marker."""

        class _BigRepr:
            def __str__(self) -> str:
                return "X" * 300

        obj = _BigRepr()
        result = _format_input(obj, limit=50)  # type: ignore[arg-type]
        assert "(truncated)" in result, (
            f"str(data) fallback must also truncate past limit: {result!r}"
        )

    def test_empty_dict_produces_braces(self):
        """An empty dict must produce '{}'."""
        result = _format_input({}, limit=1000)
        parsed = json.loads(result)
        assert parsed == {}

    def test_unicode_preserved(self):
        """Unicode values must be preserved (ensure_ascii=False)."""
        data = {"emoji": "hello 🔧 world"}
        result = _format_input(data, limit=1000)
        assert "🔧" in result, (
            f"Unicode must be preserved (ensure_ascii=False): {result!r}"
        )


# ---------------------------------------------------------------------------
# 3. tool_preview
# ---------------------------------------------------------------------------

class TestToolPreview:
    """tool_preview: first matching key, first line, capped at 60 chars."""

    def test_first_matching_key_value_returned(self):
        """The value for the first key found in block.input must be returned."""
        block = _tool_block(input={"command": "ls -la"})
        result = tool_preview(block, keys=("command",))
        assert "ls -la" in result, (
            f"Expected 'ls -la' in preview, got: {result!r}"
        )

    def test_first_of_multiple_keys_wins(self):
        """When multiple keys match, the first key in the tuple wins."""
        block = _tool_block(input={"command": "echo hi", "path": "/tmp"})
        result = tool_preview(block, keys=("command", "path"))
        assert "echo hi" in result, (
            f"First matching key 'command' must win: {result!r}"
        )
        assert "/tmp" not in result, (
            f"Second key 'path' must not appear when first key matches: {result!r}"
        )

    def test_second_key_used_when_first_absent(self):
        """When the first key is absent but the second is present, use the second."""
        block = _tool_block(input={"path": "/home/user"})
        result = tool_preview(block, keys=("command", "path"))
        assert "/home/user" in result, (
            f"Expected second key 'path' value in preview: {result!r}"
        )

    def test_no_matching_key_returns_empty_string(self):
        """When no key in the tuple is found in block.input, return ''."""
        block = _tool_block(input={"unrelated": "value"})
        result = tool_preview(block, keys=("command", "path"))
        assert result == "", (
            f"Expected '' when no key matches, got: {result!r}"
        )

    def test_empty_keys_tuple_returns_empty_string(self):
        """An empty keys tuple must return ''."""
        block = _tool_block(input={"command": "ls"})
        result = tool_preview(block, keys=())
        assert result == "", f"Expected '' for empty keys tuple: {result!r}"

    def test_empty_input_returns_empty_string(self):
        """An empty input dict must return ''."""
        block = _tool_block(input={})
        result = tool_preview(block, keys=("command",))
        assert result == "", f"Expected '' for empty input: {result!r}"

    def test_value_under_60_chars_no_ellipsis(self):
        """A value under 60 chars must appear without a trailing ellipsis."""
        short_value = "echo hello"  # 10 chars
        block = _tool_block(input={"command": short_value})
        result = tool_preview(block, keys=("command",))
        assert "…" not in result, (
            f"No ellipsis for short value: {result!r}"
        )
        assert short_value in result

    def test_value_exactly_60_chars_no_ellipsis(self):
        """A value of exactly 60 chars must appear without a trailing ellipsis."""
        exact = "A" * 60
        block = _tool_block(input={"command": exact})
        result = tool_preview(block, keys=("command",))
        assert "…" not in result, (
            f"No ellipsis for 60-char value: {result!r}"
        )

    def test_value_over_60_chars_capped_with_ellipsis(self):
        """A value exceeding 60 chars must be capped at 60 chars + '…'."""
        long_value = "Z" * 100
        block = _tool_block(input={"command": long_value})
        result = tool_preview(block, keys=("command",))
        assert "…" in result, (
            f"Ellipsis must appear for 100-char value: {result!r}"
        )
        # The capped content part (before the leading '· ') should be 60 chars
        # tool_preview returns '· <capped_line>…'
        # Strip the leading '· '
        assert result.startswith("· "), (
            f"tool_preview must prefix with '· ': {result!r}"
        )
        content_part = result[len("· "):]
        # content_part = first_60_chars + "…"
        assert len(content_part) == 61, (  # 60 chars + 1 ellipsis char
            f"Expected 61 chars (60 + ellipsis) in capped value, got {len(content_part)}: "
            f"{content_part!r}"
        )

    def test_first_line_only_for_multiline_value(self):
        """Only the first line of a multi-line value must be used."""
        block = _tool_block(input={"command": "line1\nline2\nline3"})
        result = tool_preview(block, keys=("command",))
        assert "line1" in result, f"First line must appear: {result!r}"
        assert "line2" not in result, f"Second line must not appear: {result!r}"
        assert "line3" not in result, f"Third line must not appear: {result!r}"

    def test_multiline_first_line_over_60_capped(self):
        """When the first line exceeds 60 chars, it must be capped with '…'."""
        first_line = "X" * 80
        block = _tool_block(input={"command": f"{first_line}\nsecond line"})
        result = tool_preview(block, keys=("command",))
        assert "…" in result, f"Ellipsis must appear for capped first line: {result!r}"
        assert "second" not in result, f"Second line must not appear: {result!r}"

    def test_server_block_preview_works(self):
        """tool_preview works identically with ServerToolUseBlock."""
        block = _server_block("web_search", {"query": "hello world"})
        result = tool_preview(block, keys=("query",))
        assert "hello world" in result, (
            f"Expected 'hello world' in server block preview: {result!r}"
        )

    def test_preview_result_prefixed_with_bullet(self):
        """When a matching key is found, the result must start with '· '."""
        block = _tool_block(input={"command": "echo"})
        result = tool_preview(block, keys=("command",))
        assert result.startswith("· "), (
            f"tool_preview must start with '· ': {result!r}"
        )


# ---------------------------------------------------------------------------
# 4. ToolGroupCard: _contents declared as None before compose
# ---------------------------------------------------------------------------

class TestToolGroupCardContentsDeclaration:
    """ToolGroupCard.__init__ must declare self._contents = None so type checkers
    see the attribute even before compose() is called."""

    def test_contents_attribute_exists_after_init(self):
        """self._contents must exist immediately after __init__ — no AttributeError."""
        group = _make_group()
        assert hasattr(group, "_contents"), (
            "ToolGroupCard must declare self._contents in __init__"
        )

    def test_contents_is_none_before_compose(self):
        """Before compose() is called self._contents must be None."""
        group = _make_group()
        assert group._contents is None, (
            f"self._contents must be None before compose(); got {group._contents!r}"
        )

    def test_names_list_initialized_empty(self):
        """self._names must be an empty list after __init__."""
        group = _make_group()
        assert group._names == [], (
            f"self._names must be [] after __init__; got {group._names!r}"
        )

    def test_max_input_chars_stored(self):
        """self._max_input_chars must match the constructor argument."""
        group = ToolGroupCard(max_input_chars=999, preview_keys=("command",))
        assert group._max_input_chars == 999

    def test_preview_keys_stored(self):
        """self._preview_keys must match the constructor argument."""
        keys = ("command", "path")
        group = ToolGroupCard(max_input_chars=400, preview_keys=keys)
        assert group._preview_keys == keys
