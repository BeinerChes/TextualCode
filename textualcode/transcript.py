"""Transcript: a local, zero-cost text record of the conversation.

The SDK holds the authoritative conversation inside the client; we keep a light
parallel copy so the harvester can hand it to a cheap model WITHOUT making any
call against the live session. Pure local string accumulation — no tokens, no
network. Honors the project's "wrapper adds zero billed tokens" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock


@dataclass
class Transcript:
    """An append-only list of human-readable turn lines."""

    _turns: list[str] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        text = text.strip()
        if text:
            self._turns.append(f"USER: {text}")

    def add_assistant(self, message: AssistantMessage) -> None:
        """Record an assistant turn's text and any tool calls it made."""
        for block in message.content:
            if isinstance(block, TextBlock):
                text = block.text.strip()
                if text:
                    self._turns.append(f"ASSISTANT: {text}")
            elif isinstance(block, ToolUseBlock):
                self._turns.append(f"TOOL_CALL: {block.name}")

    def clear(self) -> None:
        self._turns.clear()

    @property
    def empty(self) -> bool:
        return not self._turns

    def render(self) -> str:
        return "\n\n".join(self._turns)
