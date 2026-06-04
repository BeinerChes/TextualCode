"""Collapsible cards that render streamed tool calls."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import ServerToolUseBlock, ToolUseBlock
from rich.markup import escape
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.widgets import Collapsible, Static

# Maximum display length of the joined tool-name list in the group summary title.
# Names are truncated to this length (with a trailing ellipsis) to keep the title
# on one line.  The slice uses _SUMMARY_NAME_LIMIT - 1 so the ellipsis lands at
# exactly _SUMMARY_NAME_LIMIT visible characters.
_SUMMARY_NAME_LIMIT = 48


def tool_preview(block: ToolUseBlock | ServerToolUseBlock, keys: tuple[str, ...]) -> str:
    """A short, single-line summary of a tool call for the card title."""
    # block.input is typed dict[str, Any] by both ToolUseBlock and
    # ServerToolUseBlock in the SDK; the isinstance guard is kept intentionally as
    # defensive distrust of future SDK shape changes (e.g. a plain-str input path).
    data = block.input if isinstance(block.input, dict) else {}
    for key in keys:
        value = data.get(key)
        if value:
            line = str(value).splitlines()[0]
            return f"· {line[:60]}" + ("…" if len(line) > 60 else "")
    return ""


def _format_input(data: dict[str, Any], limit: int) -> str:
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > limit:
        text = text[:limit] + "\n… (truncated)"
    return text


class ToolCard(Collapsible):
    """A collapsible card showing a tool call: preview title + pretty JSON."""

    def __init__(
        self,
        block: ToolUseBlock | ServerToolUseBlock,
        *,
        max_input_chars: int,
        preview_keys: tuple[str, ...],
    ) -> None:
        body = _format_input(block.input, max_input_chars)
        # escape() neutralizes model-controlled name and preview before Textual
        # parses the title string as Rich markup (Content.from_text markup=True).
        title = f"🔧 {escape(block.name)}  {escape(tool_preview(block, preview_keys))}".rstrip()
        super().__init__(
            Static(Syntax(body, "json", word_wrap=True)),
            title=title,
            collapsed=True,
            classes="tool",
        )


class ToolGroupCard(Collapsible):
    """One compact, expandable line standing in for a run of tool calls.

    Collapsed it reads `🔧 N tools called · Read, Glob, …`; expanded it reveals
    the individual `ToolCard`s. Tools stream in across messages, so cards are
    mounted into the group incrementally via `add_tool`.
    """

    def __init__(
        self,
        *,
        max_input_chars: int,
        preview_keys: tuple[str, ...],
    ) -> None:
        self._max_input_chars = max_input_chars
        self._preview_keys = preview_keys
        self._names: list[str] = []
        self._contents: Collapsible.Contents | None = None
        super().__init__(title="🔧 tools…", collapsed=True, classes="tool-group")

    def compose(self) -> ComposeResult:
        # Same shape as Collapsible.compose, but we keep a handle on the
        # Contents container so add_tool can mount new cards into it after
        # mount (mounting onto the Collapsible itself would escape the
        # collapse toggle, which only hides the Contents child).
        yield self._title
        self._contents = self.Contents()
        with self._contents:
            yield from self._contents_list

    async def add_tool(self, block: ToolUseBlock | ServerToolUseBlock) -> None:
        self._names.append(block.name)
        await self._contents.mount(
            ToolCard(
                block,
                max_input_chars=self._max_input_chars,
                preview_keys=self._preview_keys,
            )
        )
        self.title = self._summary()

    def _summary(self) -> str:
        n = len(self._names)
        noun = "tool" if n == 1 else "tools"
        # escape() each model-controlled name before joining so the joined string
        # is safe to pass as a Collapsible title (markup=True sink via _watch_title).
        names = ", ".join(escape(name) for name in self._names)
        if len(names) > _SUMMARY_NAME_LIMIT:
            names = names[: _SUMMARY_NAME_LIMIT - 1] + "…"
        return f"🔧 {n} {noun} called · {names}"
