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

import secrets
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from .prompts import REVIEW_PROMPT

# Read-only inspection + web research. `tools` restricts what the isolated
# client can call; under permission_mode="bypassPermissions" the read-only
# invariant is enforced by `tools` (and `disallowed_tools`) alone.
# WebFetch is included so the reviewer can verify best practices against live
# docs; residual risk: a malicious diff could craft a directive causing the
# reviewer to fetch an attacker-controlled URL (SSRF/data exfil via URL params).
# The sentinel fence below mitigates prompt-injection to instructions; SSRF
# remains a conscious residual.
_REVIEW_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]

# Defense-in-depth: explicitly block mutating tools even though they are absent
# from _REVIEW_TOOLS. Verified: ClaudeAgentOptions.disallowed_tools exists in
# claude-agent-sdk 0.2.88 (types.py line 1666).
_DISALLOWED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"]

# Conservative resource caps for an unattended review sub-agent.
# max_turns: a diff review should never need more than ~20 back-and-forth turns.
# max_budget_usd: hard ceiling to prevent runaway cost from large diffs.
# Verified: both fields exist on ClaudeAgentOptions in 0.2.88 (types.py
# lines 1653 and 1659).
_MAX_TURNS = 20
_MAX_BUDGET_USD = 0.50


@dataclass
class ReviewResult:
    """A finished review: the markdown report plus what it cost."""

    text: str = ""
    usage: dict | None = None
    cost: float | None = None
    is_error: bool = False  # populated from ResultMessage.is_error (0.2.88 types.py L1151)


class Reviewer:
    """Runs one isolated review query over a diff and returns the report."""

    def __init__(self, model: str | None = None, cwd: str | Path | None = None) -> None:
        # `model` is the main session's CLI value; "default"/None both mean
        # "let the CLI pick", matching AgentSession._normalize_model.
        self._model = None if model in (None, "default") else model
        # ClaudeAgentOptions.cwd accepts str | Path | None (verified: 0.2.88
        # types.py line 1699).
        self._cwd: str | Path | None = cwd

    async def run(self, diff_text: str) -> ReviewResult:
        # Per-run random sentinel: wrapping the untrusted diff prevents embedded
        # directives from escaping the data boundary and becoming instructions.
        sentinel = secrets.token_hex(16)
        options = ClaudeAgentOptions(
            system_prompt=REVIEW_PROMPT,
            model=self._model,
            cwd=self._cwd,
            tools=_REVIEW_TOOLS,
            disallowed_tools=_DISALLOWED_TOOLS,
            permission_mode="bypassPermissions",  # autonomous; tools are read-only
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
                f"Review the following uncommitted working-tree diff:\n\n<untrusted-diff-{sentinel}>\n{diff_text}\n</untrusted-diff-{sentinel}>"
            )
            # receive_response() yields all messages and stops automatically
            # after the ResultMessage (verified: client.py ~L603 in 0.2.88).
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    usage = message.usage
                    cost = message.total_cost_usd
                    is_error = message.is_error
        return ReviewResult(
            text="".join(parts).strip(),
            usage=usage,
            cost=cost,
            is_error=is_error,
        )
