"""Committer: turn a diff into a commit message via a cheap model.

The Commit button runs this to draft a commit message from the uncommitted diff
(Haiku by default), then the app stages everything and commits. Like the
harvester it uses a throwaway, fully isolated SDK client with no tools — it only
emits text — and never touches the live conversation session.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from .prompts import COMMIT_PROMPT

# Defense-in-depth: explicitly block mutating tools even though tools=[].
# Verified: ClaudeAgentOptions.disallowed_tools exists in claude-agent-sdk 0.2.88
# (types.py line 1666).
_DISALLOWED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"]

# Conservative resource caps for an unattended one-shot sub-agent.
# max_turns: a commit-message draft is a single response; 2 gives one retry.
# max_budget_usd: hard ceiling for a cheap Haiku one-shot call.
# Verified: both fields exist on ClaudeAgentOptions in 0.2.88 (types.py
# lines 1653 and 1659).
_MAX_TURNS = 2
_MAX_BUDGET_USD = 0.10


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
    is_error: bool = False  # populated from ResultMessage.is_error (0.2.88 types.py L1151)


class Committer:
    """Runs one isolated query that drafts a commit message from a diff."""

    def __init__(self, model: str = "haiku") -> None:
        self._model = model

    async def run(self, diff_text: str) -> CommitMessage:
        # Per-run random sentinel: wrapping the untrusted diff prevents embedded
        # directives from escaping the data boundary and becoming instructions.
        sentinel = secrets.token_hex(16)
        options = ClaudeAgentOptions(
            system_prompt=COMMIT_PROMPT,
            model=self._model,
            tools=[],                # no tools — it only emits the message text
            disallowed_tools=_DISALLOWED_TOOLS,
            strict_mcp_config=True,
            setting_sources=[],      # fully isolated, like the main session
            max_turns=_MAX_TURNS,
            max_budget_usd=_MAX_BUDGET_USD,
        )
        parts: list[str] = []
        usage: dict | None = None
        cost: float | None = None
        is_error: bool = False
        async with ClaudeSDKClient(options=options) as client:
            await client.query(
                f"Write a commit message for the change in this diff:\n\n"
                f"<untrusted-diff-{sentinel}>\n{diff_text}\n</untrusted-diff-{sentinel}>"
            )
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    usage = message.usage
                    cost = message.total_cost_usd
                    is_error = message.is_error
        return CommitMessage(
            text=_strip_fences("".join(parts)), usage=usage, cost=cost, is_error=is_error
        )
