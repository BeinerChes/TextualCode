"""TextualCodeApp: the Textual application — wiring only.

It composes the UI and connects three collaborators: an `AgentSession` (SDK),
a `CommandRouter` (slash commands), and a `MessageRenderer` (display). Behaviour
lives in those modules; this class just orchestrates them.
"""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import Iterable

import anyio
from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from .accounting import TurnAccountant
from .agent import AgentSession
from .dispatcher import MessageDispatcher, TaskDebugLog
from .commands import CommandRouter, UnknownCommand
from .config import (
    BUILTIN_TOOLS,
    DEFAULT_MODEL,
    ProjectConfig,
    Settings,
    match_model,
)
from .errors import report_error
from .groups import AGENT, CONNECT, HARVEST, INTERRUPT, PUMP, STATS, TOOLS_UI
from .status import StatusPresenter, StatsView
from .harvest import Harvester
from .lessons import write_harvest
from .modal_bridge import ModalBridge
from .renderer import MessageRenderer
from .transcript import Transcript
from .screens import (
    ConfirmDialog,
    ModelSelector,
    ToolSelector,
)
from .widgets import ConversationView, PromptInput, StatsPanel, TaskPanel, ThinkingBar

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


class TextualCodeApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "request_quit", "Quit"),
        ("ctrl+t", "toggle_stats", "Stats"),
        ("escape", "interrupt", "Interrupt"),
    ]

    # Window (seconds) during which a second Ctrl+C confirms quit.
    _QUIT_WINDOW = 3.0

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings or Settings()
        self._project_dir = Path.cwd()
        self._project = ProjectConfig.load(self._project_dir)
        self._model_label = self._project.model
        self._modal = ModalBridge(self)
        self._agent = AgentSession(
            self._settings,
            permission_handler=self._modal.ask_permission,
            question_handler=self._modal.ask_question,
            model=self._project.model,
            tools=self._project.tools,
        )
        self._commands = CommandRouter()
        self._accountant = TurnAccountant()
        self._stats = self._accountant.stats  # alias — StatsView reads this directly
        self._transcript = Transcript()
        self._last_context: dict | None = None
        self._models: list[dict] = []  # populated after connect
        self._quit_armed = False  # True while the "press again" window is open
        self._quit_timer = None
        # True only while a real agent turn is in flight (submit → ResultMessage).
        # Distinguishes an interruptible turn from a /harvest, which also animates
        # the ThinkingBar but runs an isolated client. Esc only interrupts a turn.
        self._agent_turn_active = False
        # Set in on_mount once the widgets exist.
        self._conversation: ConversationView
        self._renderer: MessageRenderer
        self._stats_panel: StatsPanel
        self._task_panel: TaskPanel
        self._thinking: ThinkingBar
        # Presenters — constructed here; StatsView.render() only safe after on_mount.
        self._status = StatusPresenter(self)
        self._stats_view = StatsView(self)

    # ------------------------------------------------------------------ UI --
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield ConversationView(id="conversation")
            with Vertical(id="sidebar"):
                yield StatsPanel(id="stats")
                yield TaskPanel(id="tasks")
        yield ThinkingBar(id="thinking")
        yield PromptInput(placeholder="Ask anything… (or drop a file)", id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "TextualCode"
        self._status.set_phase("connecting…")
        self._conversation = self.query_one(ConversationView)
        self._stats_panel = self.query_one(StatsPanel)
        self._task_panel = self.query_one(TaskPanel)
        self._thinking = self.query_one(ThinkingBar)
        self._stats_view.render()
        self._renderer = MessageRenderer(self._conversation, self._settings)
        self._dispatcher = MessageDispatcher(
            renderer=self._renderer,
            transcript=self._transcript,
            task_panel=self._task_panel,
            debug_log=TaskDebugLog(self._project_dir),
            on_turn_complete=self._on_turn_complete,
            accrue_subagent_tokens=self._accountant.accrue_subagent_tokens,
        )
        self._commands.register("model", self.switch_model)
        self._commands.register("stats", self._toggle_stats_command)
        self._commands.register("tools", self._tools_command)
        self._commands.register("harvest", self._harvest_command)
        await self._conversation.add_markdown(WELCOME)
        self.query_one(PromptInput).focus()
        self.connect_agent()

    def action_request_quit(self) -> None:
        """Claude-Code-style quit: the first Ctrl+C arms a short confirm window
        and shows a hint; a second Ctrl+C within the window actually exits.

        This keeps a stray Ctrl+C (e.g. a terminal copy) from killing the app.
        """
        if self._quit_armed:
            self.exit()
            return
        self._quit_armed = True
        if not self._thinking.show_notice("[yellow]Press Ctrl+C again to exit[/yellow]"):
            # ThinkingBar is busy animating — fall back to a toast.
            self.notify("Press Ctrl+C again to exit", severity="warning", timeout=self._QUIT_WINDOW)
        self._quit_timer = self.set_timer(self._QUIT_WINDOW, self._disarm_quit)

    def _disarm_quit(self) -> None:
        self._quit_armed = False
        self._quit_timer = None
        self._thinking.clear_notice()

    def action_interrupt(self) -> None:
        """Esc: interrupt the in-flight turn, like Claude Code.

        No-op when the agent isn't working, so a stray Esc does nothing. Esc
        bubbles up from the focused PromptInput because its `tab_behavior` is
        "focus" (TextArea only consumes Esc under "indent").
        """
        if not self._agent_turn_active:
            return
        self.interrupt_agent()

    def action_toggle_stats(self) -> None:
        self._stats_panel.display = not self._stats_panel.display

    async def _toggle_stats_command(self, arg: str) -> None:
        self.action_toggle_stats()

    async def _harvest_command(self, arg: str) -> None:
        self.harvest_now()

    def action_harvest(self) -> None:
        """Action target for the clickable '⟳ harvest' link in the stats panel."""
        self.harvest_now()

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
    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one(PromptInput).value = ""

        if text.startswith("/"):
            try:
                await self._commands.dispatch(text)
            except UnknownCommand as exc:
                await self._conversation.add_markdown(
                    f"> Unknown command `/{exc.name}`. Try `/model`."
                )
            return

        await self._conversation.add_message("user", text)
        self._transcript.add_user(text)
        if not self._agent.connected:
            await self._conversation.add_markdown("> Agent not connected yet — try again in a moment.")
            return
        self.send_to_agent(text)

    async def on_prompt_input_file_dropped(self, message: PromptInput.FileDropped) -> None:
        name = Path(message.path).name
        await self._conversation.add_markdown(
            f"> 📎 Added `{name}` to the prompt — ask me to read or review it."
        )

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
            await report_error(
                self._conversation, None, exc,
                message=f"> **Could not switch model:** {exc}",
            )
            return

        self._model_label = value
        self._project.model = value
        self._project.save(self._project_dir)
        self._status.set_phase()
        self._stats_view.render()
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
    @work(exclusive=True, group=CONNECT)
    async def connect_agent(self) -> None:
        try:
            await self._agent.connect()
            self._models = self._agent.available_models()
            self._status.set_phase()
            self.read_agent_stream()  # start reading the message stream
        except Exception as exc:  # noqa: BLE001 - surface startup failures
            self._status.set_phase("offline")
            await report_error(
                self._conversation, None, exc,
                message=(
                    f"> **Could not start the agent.** {type(exc).__name__}: {exc}\n>\n"
                    "> Make sure the Claude Code CLI is installed and logged in."
                ),
            )

    def _abandon_turn(self) -> None:
        """Reset turn UI when a reconnect/restart abandons an in-flight turn (bug #1)."""
        self._agent_turn_active = False
        self._thinking.stop()
        self._renderer.last_usage = None
        self._renderer.last_cost = None
        self._renderer.last_model_usage = None

    async def _reconnect_and_rebind(self) -> None:
        """Abandon any in-flight turn, cancel the old pump, reconnect, start a fresh pump."""
        self._abandon_turn()
        self.workers.cancel_group(self, PUMP)   # sdk-03: stop the old pump before tearing down its client
        await self._agent.reconnect()
        self.read_agent_stream()

    @work(exclusive=True, group=CONNECT)
    async def reconnect_agent(self) -> None:
        tools = self._agent.tools
        desc = "all" if tools is None else ("none" if not tools else f"{len(tools)} selected")
        self._status.set_phase("reconnecting…")
        try:
            await self._reconnect_and_rebind()
            self._status.set_phase()
            await self._conversation.add_markdown(
                f"> ↻ Reconnected · system tools: **{desc}** "
                "(new session — conversation reset)."
            )
        except Exception as exc:  # noqa: BLE001 - surface reconnect failures
            self._status.set_phase("offline")
            await report_error(self._conversation, "Reconnect failed:", exc)

    @work(exclusive=True, group=CONNECT)
    async def restart_session(self) -> None:
        """Free the context window: tear down the SDK client and start a fresh
        session (the supported reset — there's no in-process clear API yet).

        Also clears the local transcript and cached context fill so the next
        harvest reflects only the new session. The on-screen log is untouched.
        """
        self._status.set_phase("restarting…")
        try:
            await self._reconnect_and_rebind()
            self._transcript.clear()
            self._last_context = None
            self._stats_view.render()
            self._status.set_phase()
            await self._conversation.add_markdown(
                "> ↻ **Session restarted** — context window cleared. The agent "
                "starts fresh; reference `state.md` to restore where we left off."
            )
        except Exception as exc:  # noqa: BLE001 - surface restart failures
            self._status.set_phase("offline")
            await report_error(self._conversation, "Restart failed:", exc)

    @work(exclusive=True, group=PUMP)
    async def read_agent_stream(self) -> None:
        """Single long-lived reader of the SDK message stream.

        Routes conversation messages to the renderer and Task* lifecycle
        messages to the task panel — so background work is shown even between
        turns. exclusive+group means reconnect cancels the old pump.

        Bug #3 fix: dispatch errors are caught per-message (inner try) so they
        surface to the user and reset the turn UI, but the pump loop survives.
        The outer try catches only expected stream-termination: re-raises
        CancelledError (worker cancellation) and swallows anyio.ClosedResourceError
        (stream closed on disconnect/reconnect). Verified against installed
        claude-agent-sdk v0.2.88 source (_internal/query.py, client.py) — the
        receive_messages() path wraps anyio memory streams; ClosedResourceError is
        the exception class anyio raises when a stream is closed mid-iteration.
        """
        try:
            async for message in self._agent.messages():
                try:
                    await self._dispatcher.handle(message)
                except Exception as exc:  # noqa: BLE001 - dispatch error: report and continue
                    await report_error(self._conversation, "Render error", exc)
                    self._thinking.stop()
                    self._agent_turn_active = False
        except asyncio.CancelledError:
            raise  # never swallow worker cancellation
        except anyio.ClosedResourceError:
            pass  # stream closed on disconnect/reconnect — expected termination
        except Exception as exc:  # noqa: BLE001 - unexpected stream error: surface, don't crash the app
            # Narrowing the catch (bug #3) means an unforeseen stream-level error
            # would otherwise escape the worker and, under @work's default
            # exit_on_error=True, kill the whole app. Surface it and end the pump
            # gracefully instead (a reconnect can restart the stream).
            self._thinking.stop()
            self._agent_turn_active = False
            await report_error(self._conversation, "Message stream error", exc)

    def _on_turn_complete(self) -> None:
        self._agent_turn_active = False
        self._thinking.stop()
        self._accountant.commit_turn(
            last_usage=self._renderer.last_usage,
            last_cost=self._renderer.last_cost,
            last_model_usage=self._renderer.last_model_usage,
            main_models=self._renderer.main_models,
        )
        self._renderer.last_usage = None
        self._renderer.last_cost = None
        self._renderer.last_model_usage = None
        self._status.set_phase()
        self.refresh_context()

    @work(exclusive=True, group=STATS)
    async def refresh_context(self) -> None:
        self._last_context = await self._agent.context_usage()
        self._stats_view.render()

    @work(exclusive=True, group=TOOLS_UI)
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

    @work(exclusive=True, group=TOOLS_UI)
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

    @work(exclusive=True, group=AGENT)
    async def send_to_agent(self, text: str) -> None:
        """Submit the prompt; the message pump renders the streamed response."""
        self._thinking.start()
        self._agent_turn_active = True
        self._renderer.last_cost = None
        self._renderer.last_usage = None
        self._renderer.last_model_usage = None
        self._accountant.begin_turn()
        try:
            await self._agent.submit(text)
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            self._agent_turn_active = False
            self._thinking.stop()
            await report_error(self._conversation, "Error:", exc)

    @work(exclusive=True, group=INTERRUPT)
    async def interrupt_agent(self) -> None:
        """Send the interrupt to the SDK and stop the thinking bar immediately.

        The CLI ends the turn and a ResultMessage arrives on the pump (which
        also calls `_on_turn_complete` → `stop()`), but we stop here too so the
        UI reacts instantly to the keypress.
        """
        if not self._agent_turn_active:
            return
        self._agent_turn_active = False  # don't let a second Esc re-fire
        try:
            await self._agent.interrupt()
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            await report_error(self._conversation, "Interrupt failed:", exc)
            return
        self._thinking.stop()
        await self._conversation.add_markdown("> ⏹ Interrupted.")

    @work(exclusive=True, group=HARVEST)
    async def harvest_now(self) -> None:
        """Map the session to disk via a cheap Haiku call (explicit user spend).

        Non-destructive: writes `.claude/state.md` plus any new lessons under
        `.claude/lessons/`; the live conversation session is untouched.
        """
        if self._transcript.empty:
            await self._conversation.add_markdown(
                "> Nothing to harvest yet — have a conversation first."
            )
            return
        await self._conversation.add_markdown("> ⟳ Harvesting this session with Haiku…")
        # Cold-starting an isolated Haiku client takes 15-30s with no streamed
        # output; show the animated bar so the harvest doesn't look frozen.
        self._thinking.start(label="Harvesting")
        try:
            result = await Harvester(model="haiku").run(self._transcript.render())
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            self._thinking.stop()
            await report_error(self._conversation, "Harvest failed:", exc)
            return
        try:
            paths = write_harvest(self._project_dir, result)
        except Exception as exc:  # noqa: BLE001 - report write failures cleanly
            self._thinking.stop()
            await report_error(self._conversation, "Could not write harvest files:", exc)
            return
        self._thinking.stop()
        cost = f" · ${result.cost:.4f}" if result.cost else ""
        added = len(paths.new_lessons)
        lessons_note = f", +{added} lesson(s)" if added else ""
        await self._conversation.add_markdown(
            f"> ✅ Harvested → `{paths.root.name}/state.md`{lessons_note}{cost}."
        )
        # Offer to free the context window by restarting the SDK session. This
        # runs in a worker, so push_screen_wait is safe (unlike the SDK-callback
        # dialogs, which must use push_screen + Future).
        restart = await self.push_screen_wait(
            ConfirmDialog(
                "↻ Restart session?",
                "Harvest saved. Restart the agent session to clear the context "
                "window? The agent starts fresh from an empty context; this "
                "on-screen log stays. (Your saved state.md seeds the next run.)",
                confirm_label="Restart (y)",
                cancel_label="Keep session (n)",
            )
        )
        if restart:
            self.restart_session()

    @work(group=AGENT)
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
