"""TextualCodeApp: the Textual application — wiring only.

It composes the UI and connects three collaborators: an `AgentSession` (SDK),
a `CommandRouter` (slash commands), and a `MessageRenderer` (display). Behaviour
lives in those modules; this class just orchestrates them.
"""

from __future__ import annotations

import asyncio
import os
from functools import partial
from pathlib import Path
from typing import Iterable

from claude_agent_sdk import (
    ResultMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
)
from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from .agent import AgentSession
from .commands import CommandRouter, UnknownCommand
from .config import (
    BUILTIN_TOOLS,
    DEFAULT_MODEL,
    ProjectConfig,
    Settings,
    match_model,
)
from .permissions import Decision, describe_key, similarity_key
from .renderer import MessageRenderer
from .screens import ModelSelector, PermissionDialog, ToolSelector
from .stats import UsageStats
from .widgets import ConversationView, StatsPanel, TaskPanel

WELCOME = """\
# TextualCode

Powered by the **Claude Agent SDK**. Type a message and press **Enter**.

- Uses your Claude Code login (Pro/Max subscription or `ANTHROPIC_API_KEY`).
- Tool calls prompt an **approve/deny** dialog (a / d).
- `/model` pick model · `/tools` pick tools · `/stats` panel
- Click **model** or **system tools** in the stats panel to change them.
- Settings persist per project in `.textualcode.json`.
- Press **Ctrl+C** to quit.
"""


def _task_key(message) -> str:
    """Card key for a start/progress message: task_id + description.

    Workflows share one task_id but vary the description per sub-agent (the
    agent's label), so this gives one card per sub-agent. Real tasks have a
    unique task_id and a stable description → one card.
    """
    return f"{getattr(message, 'task_id', '?')}:{getattr(message, 'description', '') or ''}"


class TextualCodeApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+t", "toggle_stats", "Stats"),
    ]

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings or Settings()
        self._project_dir = Path.cwd()
        self._project = ProjectConfig.load(self._project_dir)
        self._model_label = self._project.model
        self._agent = AgentSession(
            self._settings,
            permission_handler=self._ask_permission,
            model=self._project.model,
            tools=self._project.tools,
        )
        self._commands = CommandRouter()
        self._stats = UsageStats()
        self._last_context: dict | None = None
        self._models: list[dict] = []  # populated after connect
        # Set in on_mount once the widgets exist.
        self._conversation: ConversationView
        self._renderer: MessageRenderer
        self._stats_panel: StatsPanel
        self._task_panel: TaskPanel

    # ------------------------------------------------------------------ UI --
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield ConversationView(id="conversation")
            with Vertical(id="sidebar"):
                yield StatsPanel(id="stats")
                yield TaskPanel(id="tasks")
        yield Input(placeholder="Ask anything…", id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "TextualCode"
        self.sub_title = "connecting…"
        self._conversation = self.query_one(ConversationView)
        self._stats_panel = self.query_one(StatsPanel)
        self._task_panel = self.query_one(TaskPanel)
        self._stats_panel.show(self._stats, self._model_label, self._last_context)
        self._renderer = MessageRenderer(self._conversation, self._settings)
        self._commands.register("model", self.switch_model)
        self._commands.register("stats", self._toggle_stats_command)
        self._commands.register("tools", self._tools_command)
        await self._conversation.add_markdown(WELCOME)
        self.query_one("#prompt", Input).focus()
        self.connect_agent()

    def action_toggle_stats(self) -> None:
        self._stats_panel.display = not self._stats_panel.display

    async def _toggle_stats_command(self, arg: str) -> None:
        self.action_toggle_stats()

    async def _tools_command(self, arg: str) -> None:
        """`/tools` opens the selector; `/tools on|off` enables all / none."""
        choice = arg.strip().lower()
        if choice == "on":
            self._apply_tools(None)
        elif choice == "off":
            self._apply_tools([])
        elif not choice:
            self.open_tools_selector()
        else:
            await self._conversation.add_markdown(
                "> Usage: `/tools` (choose) · `/tools on` · `/tools off`."
            )

    def action_open_tools(self) -> None:
        """Action target for the clickable 'system tools' row in the panel."""
        self.open_tools_selector()

    def _apply_tools(self, tools: list[str] | None) -> None:
        self._project.tools = tools
        self._project.save(self._project_dir)
        self._agent.tools = tools
        self.reconnect_agent()

    async def _ask_permission(self, tool_name: str, tool_input: dict) -> Decision:
        """Show the approve/deny modal and wait for the user's choice.

        Uses push_screen + a Future (not push_screen_wait) because the SDK calls
        this from its own task, not a Textual worker.
        """
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        label = describe_key(similarity_key(tool_name, tool_input))

        def _resolve(result: Decision | None) -> None:
            if not future.done():
                future.set_result(result or Decision(allow=False))

        self.push_screen(PermissionDialog(tool_name, tool_input, label), _resolve)
        return await future

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Model: choose…",
            "Pick the agent model",
            self.open_model_selector,
        )
        for model in self._models:
            yield SystemCommand(
                f"Model: {model.get('displayName', model['value'])}",
                str(model.get("description", "")),
                partial(self._switch_model_worker, str(model["value"])),
            )
        yield SystemCommand(
            "System tools: choose…",
            "Pick which built-in tools are enabled",
            self.open_tools_selector,
        )
        yield SystemCommand(
            "System tools: enable all",
            "Enable all built-in tools (reconnects the agent)",
            partial(self._apply_tools, None),
        )
        yield SystemCommand(
            "System tools: disable all",
            "Disable all built-in tools (reconnects the agent)",
            partial(self._apply_tools, []),
        )

    # ------------------------------------------------------------- handlers --
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one("#prompt", Input).value = ""

        if text.startswith("/"):
            try:
                await self._commands.dispatch(text)
            except UnknownCommand as exc:
                await self._conversation.add_markdown(
                    f"> Unknown command `/{exc.name}`. Try `/model`."
                )
            return

        await self._conversation.add_message("user", text)
        if not self._agent.connected:
            await self._conversation.add_markdown("> Agent not connected yet — try again in a moment.")
            return
        self.send_to_agent(text)

    async def switch_model(self, name: str) -> None:
        if not self._agent.connected:
            await self._conversation.add_markdown("> Agent not connected yet — try again in a moment.")
            return
        if not name:
            self.open_model_selector()  # no arg → open the RadioSet picker
            return

        models = self._agent.available_models()
        value = match_model(name, models)
        try:
            await self._agent.set_model(value)
        except Exception as exc:  # noqa: BLE001 - report bad ids cleanly
            await self._conversation.add_markdown(f"> **Could not switch model:** {exc}")
            return

        self._model_label = value
        self._project.model = value
        self._project.save(self._project_dir)
        self.sub_title = f"agent sdk · {value}"
        self._stats_panel.show(self._stats, value, self._last_context)
        display = next(
            (m.get("displayName") for m in models if str(m.get("value")) == value), value
        )
        await self._conversation.add_markdown(
            f"> Model → **{display}** (`{value}`) · saved."
        )

    def action_open_model(self) -> None:
        """Action target for the clickable 'model' row in the stats panel."""
        self.open_model_selector()

    # -------------------------------------------------------------- workers --
    @work(exclusive=True, group="connect")
    async def connect_agent(self) -> None:
        try:
            await self._agent.connect()
            self._models = self._agent.available_models()
            self.sub_title = f"agent sdk · {self._model_label}"
            self.message_pump()  # start reading the message stream
        except Exception as exc:  # noqa: BLE001 - surface startup failures
            self.sub_title = "offline"
            await self._conversation.add_markdown(
                f"> **Could not start the agent.** {type(exc).__name__}: {exc}\n>\n"
                "> Make sure the Claude Code CLI is installed and logged in."
            )

    @work(exclusive=True, group="connect")
    async def reconnect_agent(self) -> None:
        tools = self._agent.tools
        desc = "all" if tools is None else ("none" if not tools else f"{len(tools)} selected")
        self.sub_title = "reconnecting…"
        try:
            await self._agent.reconnect()
            self.message_pump()  # rebind the pump to the new client
            self.sub_title = f"agent sdk · {self._model_label}"
            await self._conversation.add_markdown(
                f"> ↻ Reconnected · system tools: **{desc}** "
                "(new session — conversation reset)."
            )
        except Exception as exc:  # noqa: BLE001 - surface reconnect failures
            self.sub_title = "offline"
            await self._conversation.add_markdown(
                f"> **Reconnect failed:** {type(exc).__name__}: {exc}"
            )

    @work(exclusive=True, group="pump")
    async def message_pump(self) -> None:
        """Single long-lived reader of the SDK message stream.

        Routes conversation messages to the renderer and Task* lifecycle
        messages to the task panel — so background work is shown even between
        turns. exclusive+group means reconnect cancels the old pump.
        """
        try:
            async for message in self._agent.messages():
                await self._dispatch(message)
        except Exception:  # noqa: BLE001 - stream ends on disconnect/reconnect
            pass

    async def _dispatch(self, message) -> None:
        if isinstance(message, TaskStartedMessage):
            self._log_task(message)
            await self._task_panel.start(_task_key(message), message.description)
            return
        if isinstance(message, TaskProgressMessage):
            self._log_task(message)
            await self._task_panel.progress(_task_key(message), message.description, message.usage)
            return
        if isinstance(message, TaskNotificationMessage):
            self._log_task(message)
            # One notification ends the whole task → finish every card under it.
            await self._task_panel.finish_task(message.task_id, message.status, message.summary)
            return
        await self._renderer.render(message)
        if isinstance(message, ResultMessage):
            self._on_turn_complete()

    def _log_task(self, message) -> None:
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

    def _on_turn_complete(self) -> None:
        if self._renderer.last_usage is not None or self._renderer.last_cost is not None:
            self._stats.add_turn(self._renderer.last_usage, self._renderer.last_cost)
        self.sub_title = f"agent sdk · {self._model_label}"
        self.refresh_context()

    @work(exclusive=True, group="stats")
    async def refresh_context(self) -> None:
        self._last_context = await self._agent.context_usage()
        self._stats_panel.show(self._stats, self._model_label, self._last_context)

    @work(exclusive=True, group="tools-ui")
    async def open_model_selector(self) -> None:
        """Open the RadioSet model picker and apply the choice."""
        models = self._agent.available_models()
        if not models:
            await self._conversation.add_markdown(
                "> Models not available yet — connect first."
            )
            return
        chosen = await self.push_screen_wait(ModelSelector(models, self._model_label))
        if chosen is not None:
            await self.switch_model(chosen)

    @work(exclusive=True, group="tools-ui")
    async def open_tools_selector(self) -> None:
        """Open the SelectionList modal and apply the chosen tool set."""
        current = self._agent.tools
        enabled = list(BUILTIN_TOOLS) if current is None else current
        chosen = await self.push_screen_wait(ToolSelector(BUILTIN_TOOLS, enabled))
        if chosen is None:
            return  # cancelled
        # All selected → store None (= "all", future-proof as tools are added).
        tools = None if set(chosen) == set(BUILTIN_TOOLS) else chosen
        self._apply_tools(tools)

    @work(exclusive=True, group="agent")
    async def send_to_agent(self, text: str) -> None:
        """Submit the prompt; the message pump renders the streamed response."""
        self.sub_title = "thinking…"
        self._renderer.last_cost = None
        self._renderer.last_usage = None
        try:
            await self._agent.submit(text)
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            await self._conversation.add_markdown(f"> **Error:** {type(exc).__name__}: {exc}")
            self.sub_title = f"agent sdk · {self._model_label}"

    @work(group="agent")
    async def _switch_model_worker(self, name: str) -> None:
        """Sync-callable wrapper for the command palette."""
        await self.switch_model(name)

    async def on_unmount(self) -> None:
        try:
            await self._agent.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


def main() -> None:
    TextualCodeApp().run()


if __name__ == "__main__":
    main()
