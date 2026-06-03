"""MessageRenderer: turn streamed SDK messages into conversation widgets.

The single place that knows how each SDK message type should look on screen.
"""

from __future__ import annotations

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from .config import Settings
from .widgets import ConversationView, ToolCard


class MessageRenderer:
    def __init__(self, view: ConversationView, settings: Settings) -> None:
        self._view = view
        self._settings = settings
        self.last_cost: float | None = None
        self.last_usage: dict | None = None

    async def render(self, message: Message) -> None:
        if isinstance(message, AssistantMessage):
            await self._render_assistant(message)
        elif isinstance(message, ResultMessage):
            self.last_cost = message.total_cost_usd
            self.last_usage = message.usage

    async def _render_assistant(self, message: AssistantMessage) -> None:
        for block in message.content:
            if isinstance(block, TextBlock):
                await self._view.add_message("agent", block.text)
            elif isinstance(block, ToolUseBlock):
                await self._view.add_widget(
                    ToolCard(
                        block,
                        max_input_chars=self._settings.max_tool_input_chars,
                        preview_keys=self._settings.tool_preview_keys,
                    )
                )
