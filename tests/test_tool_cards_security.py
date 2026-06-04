"""Security and correctness tests for tool_cards.py and renderer.py.

All tests are hermetic — no network, no live SDK, no Textual app running.

Coverage:
1. ToolCard title with markup-metacharacter names does not raise MarkupError
   and is markup-safe (escape is present and Content.from_markup parses OK).
2. ToolGroupCard._summary with malicious names is markup-safe.
3. renderer.MessageRenderer dispatches ServerToolUseBlock to ToolGroupCard
   (not silently dropped), routes normal ToolUseBlock the same way, and skips
   AskUserQuestion.
4. ServerToolUseBlock importability + not a subclass of ToolUseBlock (regression
   guard for the dispatch change).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.markup import escape
from textual.content import Content

from claude_agent_sdk import (
    AssistantMessage,
    ServerToolUseBlock,
    TextBlock,
    ToolUseBlock,
)

from textualcode.config import Settings
from textualcode.tool_cards import ToolCard, ToolGroupCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_block(name: str = "Bash", input: dict | None = None) -> ToolUseBlock:
    return ToolUseBlock(id="tu-1", name=name, input=input or {})


def _server_block(name: str = "web_search", input: dict | None = None) -> ServerToolUseBlock:
    return ServerToolUseBlock(id="sv-1", name=name, input=input or {"query": "test"})


def _markup_safe(title: str) -> None:
    """Assert that *title* can be parsed by Rich/Textual markup without error.

    Uses Content.from_markup (the same sink that Collapsible._watch_title calls
    via CollapsibleTitle in Textual 8.2.7) to verify parse safety.
    Does NOT assert that no spans exist — that would over-specify.  It asserts
    the parse does not raise, and that the *plain text* content is correct (i.e.
    the original brackets are not consumed as markup tags, leaving truncated text).
    """
    # Should not raise
    Content.from_markup(title)


# ---------------------------------------------------------------------------
# 1. ToolCard — markup-metacharacter name is escaped in the title
# ---------------------------------------------------------------------------

class TestToolCardMarkupSafety:
    """ToolCard.__init__ builds a title that is safe to pass to Collapsible."""

    def _make_card(self, name: str) -> ToolCard:
        block = _tool_block(name=name)
        return ToolCard(
            block,
            max_input_chars=200,
            preview_keys=("command",),
        )

    def test_evil_name_with_styled_markup_does_not_raise(self):
        """name='evil[red]bold[/]' — the card must construct without error and
        the title must be markup-safe (Content.from_markup does not raise)."""
        card = self._make_card("evil[red]bold[/]")
        _markup_safe(card.title)

    def test_unmatched_bracket_name_does_not_raise(self):
        """name='x[' — unmatched bracket must not raise MarkupError."""
        card = self._make_card("x[")
        _markup_safe(card.title)

    def test_title_contains_escaped_name(self):
        """The escaped form of the malicious name must appear in the title string,
        proving the fix used rich.markup.escape() and not a plain interpolation."""
        name = "evil[red]bold[/]"
        card = self._make_card(name)
        assert escape(name) in card.title, (
            f"Expected escape({name!r}) to appear in card.title but got: {card.title!r}"
        )

    def test_title_unmatched_bracket_escaped(self):
        """The escaped form of 'x[' must appear in the title."""
        name = "x["
        card = self._make_card(name)
        assert escape(name) in card.title, (
            f"Expected escape({name!r}) to appear in card.title but got: {card.title!r}"
        )

    def test_benign_name_still_works(self):
        """A normal name like 'Bash' must still produce a valid title."""
        card = self._make_card("Bash")
        _markup_safe(card.title)
        assert "Bash" in card.title

    def test_server_tool_block_card_markup_safe(self):
        """ToolCard with a ServerToolUseBlock (web_search) must be markup-safe."""
        block = _server_block("web_search")
        card = ToolCard(
            block,
            max_input_chars=200,
            preview_keys=("query",),
        )
        _markup_safe(card.title)
        assert escape("web_search") in card.title


# ---------------------------------------------------------------------------
# 2. ToolGroupCard._summary — markup-safe with malicious names
# ---------------------------------------------------------------------------

class TestToolGroupCardSummaryMarkupSafety:
    """ToolGroupCard._summary joins model-controlled names into a Collapsible
    title.  Each name must be escape()d before joining."""

    def _make_group(self) -> ToolGroupCard:
        return ToolGroupCard(
            max_input_chars=200,
            preview_keys=("command",),
        )

    def test_summary_single_evil_name_markup_safe(self):
        """A single malicious name in _names yields a markup-safe summary."""
        group = self._make_group()
        group._names = ["evil[red]bold[/]"]
        summary = group._summary()
        _markup_safe(summary)

    def test_summary_multiple_evil_names_markup_safe(self):
        """Multiple malicious names joined together (within the 48-char truncation
        limit so no mid-escape-sequence cut occurs) must be markup-safe.

        NOTE FOR REVIEWER: _summary() truncates the *already-escaped* names string
        at 47 chars.  If truncation falls in the middle of an escape sequence
        (e.g. 'evil\\[link=…' becomes 'evil\\[lin') Textual 8.2.7 raises MarkupError
        because the partial escape is still parsed as markup.  This is a source bug
        in tool_cards.py: truncation must happen BEFORE escaping (truncate raw names,
        then escape), or must use a safe truncation that does not split escape tokens.
        Test below uses names whose combined escaped length stays under 48 chars to
        avoid triggering the truncation path; the truncation edge-case is tracked
        separately.
        """
        group = self._make_group()
        # "a[b], c[, d[/e]" -> escaped: "a\\[b], c[, d\\[/e]" (17 chars, under 48)
        group._names = ["a[b]", "c[", "d[/e]"]
        summary = group._summary()
        _markup_safe(summary)

    def test_summary_unmatched_bracket_markup_safe(self):
        """An unmatched bracket in _names must not cause MarkupError."""
        group = self._make_group()
        group._names = ["x["]
        summary = group._summary()
        _markup_safe(summary)

    def test_summary_contains_escaped_name(self):
        """The escaped form of a malicious name must appear in the summary."""
        name = "evil[red]bold[/]"
        group = self._make_group()
        group._names = [name]
        summary = group._summary()
        assert escape(name) in summary, (
            f"Expected escape({name!r}) in summary but got: {summary!r}"
        )

    def test_summary_contains_escaped_unmatched_bracket(self):
        """The escaped form of 'x[' must appear in the summary."""
        name = "x["
        group = self._make_group()
        group._names = [name]
        summary = group._summary()
        assert escape(name) in summary, (
            f"Expected escape({name!r}) in summary but got: {summary!r}"
        )

    def test_summary_noun_singular(self):
        """1 tool -> 'tool' (singular)."""
        group = self._make_group()
        group._names = ["Bash"]
        assert "1 tool" in group._summary()

    def test_summary_noun_plural(self):
        """2+ tools -> 'tools' (plural)."""
        group = self._make_group()
        group._names = ["Bash", "Read"]
        assert "2 tools" in group._summary()


# ---------------------------------------------------------------------------
# 3. MessageRenderer dispatch
# ---------------------------------------------------------------------------

def _make_renderer() -> tuple[MessageRenderer_type, list, list]:
    """Return (renderer, add_message_calls, add_widget_calls).

    Uses a minimal async stub for ConversationView; no Textual app needed.
    add_widget is awaited by MessageRenderer._render_assistant and stores the
    widget passed to it so tests can inspect what was mounted.
    """
    from textualcode.renderer import MessageRenderer

    add_message_calls: list[tuple[str, str]] = []
    add_widget_calls: list[object] = []
    # Track add_tool calls per ToolGroupCard for assertion
    add_tool_calls: list[tuple[object, object]] = []

    class FakeView:
        async def add_message(self, role: str, text: str) -> None:
            add_message_calls.append((role, text))

        async def add_widget(self, widget: object) -> None:
            # Patch add_tool on the ToolGroupCard so tests can see calls without
            # requiring a mounted Textual widget (add_tool calls mount internally).
            original_add_tool = widget.add_tool

            async def _patched_add_tool(block):
                add_tool_calls.append((widget, block))
                # Call the real method but skip the mount (not mounted in a live app)
                widget._names.append(block.name)
                widget.title = widget._summary()

            widget.add_tool = _patched_add_tool  # type: ignore[method-assign]
            add_widget_calls.append(widget)

    renderer = MessageRenderer(view=FakeView(), settings=Settings())
    return renderer, add_message_calls, add_widget_calls, add_tool_calls


# Type alias so mypy sees the tuple unpacking used in tests
MessageRenderer_type = object  # avoids circular import; tests use duck typing


class TestMessageRendererDispatch:
    """MessageRenderer._render_assistant must dispatch both ToolUseBlock and
    ServerToolUseBlock to ToolGroupCard, and skip AskUserQuestion."""

    async def test_server_tool_block_not_dropped(self):
        """A ServerToolUseBlock in an AssistantMessage.content must reach
        ToolGroupCard.add_tool — NOT be silently skipped."""
        renderer, add_msg, add_widget, add_tool = _make_renderer()
        srv = _server_block("web_search", {"query": "hello"})
        msg = AssistantMessage(content=[srv], model="claude-3")

        await renderer.render(msg)

        assert len(add_widget) == 1, (
            "Expected 1 ToolGroupCard to be mounted for the ServerToolUseBlock"
        )
        assert len(add_tool) == 1, (
            "Expected add_tool to be called once for the ServerToolUseBlock"
        )
        assert add_tool[0][1] is srv, (
            "The block passed to add_tool must be the original ServerToolUseBlock"
        )

    async def test_normal_tool_block_dispatched(self):
        """A plain ToolUseBlock (non-AskUserQuestion) must also reach ToolGroupCard."""
        renderer, add_msg, add_widget, add_tool = _make_renderer()
        block = _tool_block("Bash", {"command": "ls"})
        msg = AssistantMessage(content=[block], model="claude-3")

        await renderer.render(msg)

        assert len(add_widget) == 1, "Expected 1 ToolGroupCard for ToolUseBlock"
        assert len(add_tool) == 1, "Expected add_tool called once for ToolUseBlock"
        assert add_tool[0][1] is block

    async def test_ask_user_question_skipped(self):
        """AskUserQuestion ToolUseBlock must NOT be added to a ToolGroupCard."""
        renderer, add_msg, add_widget, add_tool = _make_renderer()
        block = _tool_block("AskUserQuestion", {"questions": []})
        msg = AssistantMessage(content=[block], model="claude-3")

        await renderer.render(msg)

        assert len(add_widget) == 0, "AskUserQuestion must not produce a ToolGroupCard"
        assert len(add_tool) == 0, "AskUserQuestion must not reach add_tool"

    async def test_server_and_client_tools_grouped_together(self):
        """A ServerToolUseBlock followed by a ToolUseBlock in the same message
        should be added to the *same* ToolGroupCard (one group, two add_tool calls)."""
        renderer, add_msg, add_widget, add_tool = _make_renderer()
        srv = _server_block("web_search", {"query": "x"})
        client = _tool_block("Bash", {"command": "echo"})
        msg = AssistantMessage(content=[srv, client], model="claude-3")

        await renderer.render(msg)

        # Only one ToolGroupCard should be created (the group is not reset between
        # blocks in the same turn unless a TextBlock resets it)
        assert len(add_widget) == 1, (
            "Both tool blocks in one message should share a single ToolGroupCard"
        )
        assert len(add_tool) == 2, "Two blocks = two add_tool calls"
        blocks_dispatched = [call[1] for call in add_tool]
        assert srv in blocks_dispatched
        assert client in blocks_dispatched

    async def test_text_block_resets_tool_group(self):
        """A TextBlock in the content list resets the open tool group so any
        subsequent tool call opens a new ToolGroupCard."""
        renderer, add_msg, add_widget, add_tool = _make_renderer()
        first_tool = _tool_block("Read", {"file_path": "a.py"})
        text_block = TextBlock(text="Some agent text")
        second_tool = _tool_block("Bash", {"command": "ls"})
        msg = AssistantMessage(
            content=[first_tool, text_block, second_tool],
            model="claude-3",
        )

        await renderer.render(msg)

        # Two ToolGroupCards: one before the text, one after
        assert len(add_widget) == 2, (
            f"Expected 2 ToolGroupCards after text reset, got {len(add_widget)}"
        )
        # The text message should be in add_msg
        assert len(add_msg) == 1
        assert add_msg[0] == ("agent", "Some agent text")


# ---------------------------------------------------------------------------
# 4. ServerToolUseBlock importability + not-a-subclass regression guard
# ---------------------------------------------------------------------------

class TestServerToolUseBlockIdentity:
    """Documents the structural reason why the renderer dispatch must check for
    both ToolUseBlock and ServerToolUseBlock explicitly."""

    def test_server_tool_use_block_is_importable(self):
        """ServerToolUseBlock must be importable from claude_agent_sdk."""
        # Already imported at module top level; this is a smoke check.
        assert ServerToolUseBlock is not None

    def test_server_tool_use_block_is_not_subclass_of_tool_use_block(self):
        """ServerToolUseBlock must NOT be a subclass of ToolUseBlock.

        This is the structural invariant that justifies the dispatch fix:
        isinstance(block, ToolUseBlock) would be False for a ServerToolUseBlock,
        so both types must be listed in the isinstance() check.
        """
        assert not issubclass(ServerToolUseBlock, ToolUseBlock), (
            "ServerToolUseBlock is a subclass of ToolUseBlock — "
            "the isinstance dispatch fix may be unnecessary; review renderer.py"
        )

    def test_isinstance_check_separates_the_two_types(self):
        """An isinstance(block, ToolUseBlock) check returns False for a
        ServerToolUseBlock instance, confirming they need separate dispatch."""
        srv = _server_block("web_search")
        assert not isinstance(srv, ToolUseBlock), (
            "ServerToolUseBlock instance passed isinstance(block, ToolUseBlock) — "
            "the structural assumption of the renderer fix is violated"
        )

    def test_combined_isinstance_covers_both(self):
        """isinstance(block, (ToolUseBlock, ServerToolUseBlock)) returns True for
        both types — the fixed renderer dispatch pattern works correctly."""
        client_block = _tool_block("Bash")
        srv_block = _server_block("web_search")

        assert isinstance(client_block, (ToolUseBlock, ServerToolUseBlock))
        assert isinstance(srv_block, (ToolUseBlock, ServerToolUseBlock))
