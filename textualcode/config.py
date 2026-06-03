"""Configuration: tunable settings and model-name resolution.

Pure data and helpers — no I/O, no Textual, no SDK calls.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# Per-project settings file, written in the directory the app is launched from.
CONFIG_FILENAME = ".textualcode.json"

# The CLI's selector for its recommended/default model (current latest Opus).
DEFAULT_MODEL = "default"

# Reasoning-effort levels for the SDK's connect-time `effort` option
# (ClaudeAgentOptions.effort). "default" means "leave the option unset and let
# the model decide"; the rest map 1:1 to the SDK's
# EffortLevel = Literal["low", "medium", "high", "xhigh", "max"] (verified
# against claude-agent-sdk==0.2.88, types.py). Lower effort uses fewer tokens
# per turn and is faster/cheaper; higher trades latency + cost for depth.
DEFAULT_EFFORT = "default"

EFFORT_LEVELS: tuple[dict[str, str], ...] = (
    {"value": "default", "label": "Default",
     "description": "Leave unset — the model picks its own reasoning depth."},
    {"value": "low", "label": "Low",
     "description": "Minimal reasoning, fastest — lookups, listing files."},
    {"value": "medium", "label": "Medium",
     "description": "Balanced reasoning — routine edits, standard tasks."},
    {"value": "high", "label": "High",
     "description": "Thorough analysis — refactors, debugging."},
    {"value": "xhigh", "label": "XHigh",
     "description": "Extended depth (Opus 4.7; falls back to high elsewhere)."},
    {"value": "max", "label": "Max",
     "description": "Maximum depth — hard, multi-step problems."},
)

# The valid `effort` strings a ProjectConfig / selector may hold.
EFFORT_VALUES: tuple[str, ...] = tuple(level["value"] for level in EFFORT_LEVELS)


def effort_display(value: str) -> str:
    """Human label for an effort `value` (e.g. "xhigh" -> "XHigh")."""
    for level in EFFORT_LEVELS:
        if level["value"] == value:
            return str(level["label"])
    return value


def match_model(name: str, models: list[dict]) -> str:
    """Resolve a user string to a model `value` from the live server list.

    Matches a `value` exactly, else a substring of `displayName`/`description`
    (so "opus" -> the model described as "Opus 4.8" -> value "default"). Falls
    through to the raw string so explicit ids still work.
    """
    query = name.strip().lower()
    for model in models:
        if str(model.get("value", "")).lower() == query:
            return str(model["value"])
    for model in models:
        haystack = f"{model.get('displayName', '')} {model.get('description', '')}".lower()
        if query and query in haystack:
            return str(model["value"])
    return name

# Conversation role markers (Rich markup, rendered in the message gutter).
# ▲ = you (input goes up to the model), ▼ = agent (response comes down).
USER_ICON = "[cyan]▲[/cyan]"
AGENT_ICON = "[green]▼[/green]"

# Canonical built-in Claude Code tools, for the per-tool selector. The SDK ships
# no constant list; these are the stable, well-known names.
BUILTIN_TOOLS: tuple[str, ...] = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "NotebookEdit",
    "TodoWrite",
    "Task",
    "AskUserQuestion",  # lets Claude ask clarifying questions (rendered as a form)
)

SYSTEM_PROMPT = (
    "You are TextualCode, a helpful coding assistant running inside a terminal "
    "chat. You have the full Claude Code toolset (shell, file read/write/edit, "
    "search, etc.). Keep answers concise and use Markdown."
)


@dataclass(frozen=True)
class Settings:
    """Behavioural knobs for the app, gathered in one place."""

    system_prompt: str = SYSTEM_PROMPT
    # Tool-card input longer than this is truncated in the UI.
    max_tool_input_chars: int = 2000
    tool_preview_keys: tuple[str, ...] = (
        "command",
        "file_path",
        "path",
        "pattern",
        "url",
        "query",
    )


@dataclass
class ProjectConfig:
    """User preferences persisted per project in `.textualcode.json`.

    `tools` mirrors the SDK's option: None = all built-ins, [] = none,
    [names] = exactly those.
    """

    model: str = "default"               # alias or raw id; "default" = SDK default
    tools: list[str] | None = None       # None = all built-ins; [] = none; subset = list
    effort: str = DEFAULT_EFFORT         # one of EFFORT_VALUES; "default" = unset

    @classmethod
    def load(cls, directory: Path) -> "ProjectConfig":
        path = directory / CONFIG_FILENAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(
            model=str(data.get("model", "default")),
            tools=cls._read_tools(data),
            effort=cls._read_effort(data),
        )

    @staticmethod
    def _read_effort(data: dict) -> str:
        """Accept only a known effort value; fall back to the default otherwise."""
        value = str(data.get("effort", DEFAULT_EFFORT)).strip().lower()
        return value if value in EFFORT_VALUES else DEFAULT_EFFORT

    @staticmethod
    def _read_tools(data: dict) -> list[str] | None:
        if "tools" in data:
            value = data["tools"]
            return value if (value is None or isinstance(value, list)) else None
        if "system_tools" in data:  # legacy bool: True -> all, False -> none
            return None if data.get("system_tools", True) else []
        return None

    def save(self, directory: Path) -> None:
        path = directory / CONFIG_FILENAME
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass  # non-fatal: settings just won't persist
