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
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from .prompts import EXTRACTION_PROMPT


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
        options = ClaudeAgentOptions(
            system_prompt=EXTRACTION_PROMPT,
            model=self._model,
            tools=[],                # no tools — it only emits JSON
            strict_mcp_config=True,
            setting_sources=[],      # fully isolated, like the main session
        )
        parts: list[str] = []
        usage: dict | None = None
        cost: float | None = None
        async with ClaudeSDKClient(options=options) as client:
            await client.query(transcript)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    usage = message.usage
                    cost = message.total_cost_usd
        return self._parse("".join(parts), usage, cost)

    @staticmethod
    def _parse(raw: str, usage: dict | None, cost: float | None) -> HarvestResult:
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
        )
