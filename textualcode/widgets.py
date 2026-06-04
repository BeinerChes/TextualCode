"""Presentation widgets.

This module was split into focused per-feature modules; it now re-exports the
public widgets so existing `from .widgets import ...` call sites keep working.

- `prompt_input`  — PromptInput
- `conversation`  — ConversationView
- `thinking_bar`  — ThinkingBar
- `stats_panel`   — StatsPanel
- `task_cards`    — TaskCard, TaskPanel
- `tool_cards`    — ToolCard, ToolGroupCard, tool_preview
- `formatting`    — shared helpers (_short)
"""

from __future__ import annotations

from .conversation import ConversationView
from .formatting import _short
from .prompt_input import PromptInput
from .selectable_static import SelectableStatic
from .stats_panel import StatsPanel
from .task_cards import TaskCard, TaskPanel
from .thinking_bar import ThinkingBar
from .tool_cards import ToolCard, ToolGroupCard, _format_input, tool_preview
from .workspace_panel import WorkspacePanel

__all__ = [
    "ConversationView",
    "PromptInput",
    "SelectableStatic",
    "StatsPanel",
    "TaskCard",
    "TaskPanel",
    "ThinkingBar",
    "WorkspacePanel",
    "ToolCard",
    "ToolGroupCard",
    "tool_preview",
    "_format_input",
    "_short",
]
