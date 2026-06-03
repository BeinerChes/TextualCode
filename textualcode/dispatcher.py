"""MessageDispatcher and TaskDebugLog — SDK message routing for TextualCodeApp.

Extracted from app.py (Step 2 of the app-refactor-plan). The @work pump worker
stays on the App (Textual workers must live on a MessagePump); only the routing
logic and debug logging live here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
)

if TYPE_CHECKING:
    from .renderer import MessageRenderer
    from .transcript import Transcript
    from .widgets import TaskPanel


def _task_key(message) -> str:
    """Card key for a start/progress message: task_id + description.

    Workflows share one task_id but vary the description per sub-agent (the
    agent's label), so this gives one card per sub-agent. Real tasks have a
    unique task_id and a stable description → one card.
    """
    return f"{getattr(message, 'task_id', '?')}:{getattr(message, 'description', '') or ''}"


class TaskDebugLog:
    """Env-gated (TEXTUALCODE_DEBUG_TASKS) file logger for Task* messages."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir

    def record(self, message) -> None:
        """Append raw Task* fields to a debug log when TEXTUALCODE_DEBUG_TASKS is set."""
        if not os.environ.get("TEXTUALCODE_DEBUG_TASKS"):
            return
        try:
            line = (
                f"{type(message).__name__} "
                f"task_id={getattr(message, 'task_id', '?')} "
                f"tool_use_id={getattr(message, 'tool_use_id', '')} "
                f"usage={getattr(message, 'usage', None)} "
                f"desc={getattr(message, 'description', getattr(message, 'summary', ''))!r}\n"
            )
            with (self._project_dir / "task-debug.log").open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:  # noqa: BLE001 - logging must never break the pump
            pass


class MessageDispatcher:
    """Routes SDK messages from the pump to the appropriate UI collaborators."""

    def __init__(
        self,
        *,
        renderer: "MessageRenderer",
        transcript: "Transcript",
        task_panel: "TaskPanel",
        debug_log: TaskDebugLog,
        accrue_subagent_tokens: Callable,
        on_turn_complete: Callable,
    ) -> None:
        self._renderer = renderer
        self._transcript = transcript
        self._task_panel = task_panel
        self._debug_log = debug_log
        self._accrue_subagent_tokens = accrue_subagent_tokens
        self._on_turn_complete = on_turn_complete

    async def handle(self, message) -> None:
        """Dispatch a single SDK message to the right UI collaborator(s)."""
        # Log all Task* messages once at the top (smell-07: was three separate calls).
        if isinstance(message, (TaskStartedMessage, TaskProgressMessage, TaskNotificationMessage)):
            self._debug_log.record(message)

        if isinstance(message, TaskStartedMessage):
            await self._task_panel.start(_task_key(message), message.description)
            return
        if isinstance(message, TaskProgressMessage):
            await self._task_panel.progress(_task_key(message), message.description, message.usage)
            return
        if isinstance(message, TaskNotificationMessage):
            # Accumulate the subagent's token spend for this turn's cost split.
            if message.usage:
                self._accrue_subagent_tokens(message.usage)
            # One notification ends the whole task → finish every card under it.
            await self._task_panel.finish_task(message.task_id, message.status, message.summary)
            return
        if isinstance(message, AssistantMessage):
            self._transcript.add_assistant(message)
        await self._renderer.render(message)
        if isinstance(message, ResultMessage):
            self._on_turn_complete()
