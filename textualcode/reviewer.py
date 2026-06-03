"""Reviewer: run a code review over the working-tree diff in an isolated client.

The Review button spins up a throwaway, fully isolated SDK client on the **same
model the main session is using** ("current model"), hands it the uncommitted
diff, and lets it inspect the surrounding code (read-only tools) and web-search
for current best practices. It returns a human-readable markdown report which
the app then injects into the MAIN agent's context — so "you" (the TextualCode
agent) sees the findings and can act on them.

Like the harvester, this never touches the live conversation session: it is a
separate ``ClaudeSDKClient`` with ``setting_sources=[]`` and a restricted,
read-only tool set, auto-approved so it runs without prompting the user.
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

from .prompts import REVIEW_PROMPT

# Read-only inspection + web research. No Bash/Write/Edit: the reviewer reports,
# it never mutates the tree. Listed in both `tools` (what exists) and
# `allowed_tools` (auto-approved, no permission prompt) so the isolated client —
# which has no can_use_tool handler — runs autonomously.
_REVIEW_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]


@dataclass
class ReviewResult:
    """A finished review: the markdown report plus what it cost."""

    text: str = ""
    usage: dict | None = None
    cost: float | None = None


class Reviewer:
    """Runs one isolated review query over a diff and returns the report."""

    def __init__(self, model: str | None = None, cwd=None) -> None:
        # `model` is the main session's CLI value; "default"/None both mean
        # "let the CLI pick", matching AgentSession._normalize_model.
        self._model = None if model in (None, "default") else model
        self._cwd = cwd

    async def run(self, diff_text: str) -> ReviewResult:
        options = ClaudeAgentOptions(
            system_prompt=REVIEW_PROMPT,
            model=self._model,
            cwd=self._cwd,
            tools=_REVIEW_TOOLS,
            allowed_tools=_REVIEW_TOOLS,
            permission_mode="bypassPermissions",  # autonomous; tools are read-only
            strict_mcp_config=True,
            setting_sources=[],      # fully isolated, like the main session
        )
        client = ClaudeSDKClient(options=options)
        await client.connect()
        parts: list[str] = []
        usage: dict | None = None
        cost: float | None = None
        try:
            await client.query(
                "Review the following uncommitted working-tree diff:\n\n"
                f"{diff_text}"
            )
            async for message in client.receive_messages():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    usage = message.usage
                    cost = message.total_cost_usd
                    break
        finally:
            await client.disconnect()
        return ReviewResult(text="".join(parts).strip(), usage=usage, cost=cost)
