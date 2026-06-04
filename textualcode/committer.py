"""Committer: turn a diff into a commit message via a cheap model.

The Commit button runs this to draft a commit message from the uncommitted diff
(Haiku by default), then the app stages everything and commits. Like the
harvester it uses a throwaway, fully isolated SDK client with no tools — it only
emits text — and never touches the live conversation session.
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from .prompts import COMMIT_PROMPT


def _strip_fences(text: str) -> str:
    """Drop a stray ```...``` wrapper if the model added one despite the prompt."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop the opening fence (and any language tag) and a trailing fence.
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


@dataclass
class CommitMessage:
    """A drafted commit message plus what it cost to generate."""

    text: str = ""
    usage: dict | None = None
    cost: float | None = None


class Committer:
    """Runs one isolated query that drafts a commit message from a diff."""

    def __init__(self, model: str = "haiku") -> None:
        self._model = model

    async def run(self, diff_text: str) -> CommitMessage:
        options = ClaudeAgentOptions(
            system_prompt=COMMIT_PROMPT,
            model=self._model,
            tools=[],                # no tools — it only emits the message text
            strict_mcp_config=True,
            setting_sources=[],      # fully isolated, like the main session
        )
        parts: list[str] = []
        usage: dict | None = None
        cost: float | None = None
        async with ClaudeSDKClient(options=options) as client:
            await client.query(f"Write a commit message for this diff:\n\n{diff_text}")
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    usage = message.usage
                    cost = message.total_cost_usd
        return CommitMessage(
            text=_strip_fences("".join(parts)), usage=usage, cost=cost
        )
