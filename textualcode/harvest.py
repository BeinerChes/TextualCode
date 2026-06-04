"""Harvester: turn a session transcript into a structured MAP via a cheap model.

This runs only as an EXPLICIT user action (the ⟳ harvest button / `/harvest`),
so the single model call it makes is sanctioned spend. It uses the cheapest
model (Haiku by default) and a throwaway, fully isolated SDK client — it never
touches the live conversation session.

The model is asked to MAP, not summarize: extract goal/why/actions/mistakes/
result/next plus search anchors (keywords, keyfiles) and any durable, reusable
lessons. Output is forced to a single JSON object that we parse deterministically.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from .prompts import EXTRACTION_PROMPT

# Defense-in-depth: explicitly block mutating tools even though tools=[].
# Verified: ClaudeAgentOptions.disallowed_tools exists in claude-agent-sdk 0.2.88
# (types.py line 1666).
_DISALLOWED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"]

# Conservative resource caps for an unattended one-shot sub-agent.
# max_turns: a JSON extraction is a single response; 2 gives one retry.
# max_budget_usd: hard ceiling for a cheap Haiku one-shot call.
# Verified: both fields exist on ClaudeAgentOptions in 0.2.88 (types.py
# lines 1653 and 1659).
_MAX_TURNS = 2
_MAX_BUDGET_USD = 0.10


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60].rstrip("-") or "lesson"


@dataclass
class Lesson:
    slug: str
    category: str
    rule: str


@dataclass
class HarvestResult:
    goal: str = ""
    why: str = ""
    did: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)
    result: str = ""
    satisfied: str = "unknown"
    next: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    keyfiles: list[str] = field(default_factory=list)
    lessons: list[Lesson] = field(default_factory=list)
    raw: str = ""
    usage: dict | None = None
    cost: float | None = None
    is_error: bool = False  # populated from ResultMessage.is_error (0.2.88 types.py L1151)


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if value:
        return [str(value).strip()]
    return []


def _extract_json(text: str) -> dict | None:
    """Pull the first balanced-ish JSON object out of the model's reply."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class Harvester:
    """Runs one isolated Haiku query over the transcript and parses the result."""

    def __init__(self, model: str = "haiku") -> None:
        self._model = model

    async def run(self, transcript: str) -> HarvestResult:
        # Per-run random sentinel: wrapping the untrusted transcript prevents
        # embedded directives from escaping the data boundary and becoming
        # instructions.
        sentinel = secrets.token_hex(16)
        options = ClaudeAgentOptions(
            system_prompt=EXTRACTION_PROMPT,
            model=self._model,
            tools=[],                # no tools — it only emits JSON
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
                f"<untrusted-transcript-{sentinel}>\n{transcript}\n</untrusted-transcript-{sentinel}>"
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
        return self._parse("".join(parts), usage, cost, is_error)

    @staticmethod
    def _parse(
        raw: str, usage: dict | None, cost: float | None, is_error: bool = False
    ) -> HarvestResult:
        data = _extract_json(raw) or {}
        lessons: list[Lesson] = []
        for item in data.get("lessons", []) or []:
            if isinstance(item, dict) and str(item.get("rule", "")).strip():
                rule = str(item["rule"]).strip()
                lessons.append(
                    Lesson(
                        slug=str(item.get("slug") or "").strip() or _slugify(rule),
                        category=str(item.get("category") or "General").strip() or "General",
                        rule=rule,
                    )
                )
        return HarvestResult(
            goal=str(data.get("goal", "")).strip(),
            why=str(data.get("why", "")).strip(),
            did=_as_list(data.get("did")),
            mistakes=_as_list(data.get("mistakes")),
            result=str(data.get("result", "")).strip(),
            satisfied=str(data.get("satisfied", "unknown")).strip() or "unknown",
            next=_as_list(data.get("next")),
            keywords=_as_list(data.get("keywords")),
            keyfiles=_as_list(data.get("keyfiles")),
            lessons=lessons,
            raw=raw,
            usage=usage,
            cost=cost,
            is_error=is_error,
        )
