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
from .widgets import ConversationView, ToolGroupCard


class MessageRenderer:
    def __init__(self, view: ConversationView, settings: Settings) -> None:
        self._view = view
        self._settings = settings
        self.last_cost: float | None = None
        self.last_usage: dict | None = None
        # Per-model cost/token breakdown from the turn's ResultMessage. Keyed by
        # full model id, each value has costUSD/inputTokens/outputTokens/etc.
        self.last_model_usage: dict | None = None
        # Resolved model ids used by the MAIN agent. Subagent assistant messages
        # never reach this (main) stream (verified empirically + per SDK docs:
        # only a subagent's final result returns to the parent), so any model on
        # a parent_tool_use_id=None message is a main-agent model. stats.add_turn
        # uses this to tell main spend from subagent spend in model_usage.
        self.main_models: set[str] = set()
        # The open run of consecutive tool calls, collapsed into one card. Reset
        # by any agent text or by the turn's ResultMessage so a new run starts a
        # fresh group (see _render_assistant / render).
        self._tool_group: ToolGroupCard | None = None

    async def render(self, message: Message) -> None:
        if isinstance(message, AssistantMessage):
            await self._render_assistant(message)
        elif isinstance(message, ResultMessage):
            self._tool_group = None  # turn boundary: next tools start a new group
            self.last_cost = message.total_cost_usd
            self.last_usage = message.usage
            self.last_model_usage = message.model_usage

    async def _render_assistant(self, message: AssistantMessage) -> None:
        # parent_tool_use_id is None only for the main agent; record its model(s).
        if message.model and message.parent_tool_use_id is None:
            self.main_models.add(message.model)
        for block in message.content:
            if isinstance(block, TextBlock):
                self._tool_group = None  # agent spoke: close the current tool run
                await self._view.add_message("agent", block.text)
            elif isinstance(block, ToolUseBlock):
                if block.name == "AskUserQuestion":
                    self._tool_group = None  # shown as a form, breaks the run
                    continue  # shown as an interactive form (QuestionForm), not a card
                if self._tool_group is None:
                    self._tool_group = ToolGroupCard(
                        max_input_chars=self._settings.max_tool_input_chars,
                        preview_keys=self._settings.tool_preview_keys,
                    )
                    await self._view.add_widget(self._tool_group)
                await self._tool_group.add_tool(block)
