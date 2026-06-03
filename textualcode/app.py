"""TextualCodeApp: the Textual application — composition root / wiring only.

It composes the UI and constructs the collaborators that hold the behaviour,
keeping only ``compose()``, the ``on_mount`` wiring, the Textual
``action_*``/message-handler entry points, and the thin ``@work`` worker shims.
The collaborators:

- ``AgentSession`` (SDK) + ``SessionController`` — connect/reconnect/restart.
- ``MessageDispatcher`` + ``MessageRenderer`` — route and render the stream.
- ``TurnAccountant`` — per-turn cost/usage accounting.
- ``StatusPresenter`` / ``StatsView`` — the status line and stats panel.
- ``ModalBridge`` — SDK permission/question dialogs.
- ``ModelController`` / ``ToolsController`` — model + built-in-tools features.
- ``HarvestController`` / ``QuitGuard`` — harvest flow and two-step quit.
- ``CommandRouter`` — slash commands.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

import anyio
from textual import work

from . import __version__
from textual.app import App, ComposeResult, SystemCommand
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from .accounting import TurnAccountant
from .agent import AgentSession
from .dispatcher import MessageDispatcher, TaskDebugLog
from .commands import CommandRouter, UnknownCommand
from .config import (
    BUILTIN_TOOLS,
    EFFORT_LEVELS,
    ProjectConfig,
    Settings,
)
from .errors import report_error
from .groups import (
    AGENT,
    COMMIT,
    CONNECT,
    HARVEST,
    INTERRUPT,
    PUMP,
    REVIEW,
    STATS,
    TOOLS_UI,
)
from .effort_controller import EffortController
from .harvest_controller import HarvestController
from .model_controller import ModelController
from .session_controller import SessionController
from .tools_controller import ToolsController
from .workspace_controller import WorkspaceController
from .quit_guard import QuitGuard
from .status import StatusPresenter, StatsView
from .modal_bridge import ModalBridge
from .renderer import MessageRenderer
from .transcript import Transcript
from .screens import (
    EffortSelector,
    ModelSelector,
    ToolSelector,
)
from .widgets import (
    ConversationView,
    PromptInput,
    StatsPanel,
    TaskPanel,
    ThinkingBar,
    WorkspacePanel,
)

WELCOME = f"""\
```
████████╗ ██████╗ ██████╗ ██████╗ ███████╗
╚══██╔══╝██╔════╝██╔═══██╗██╔══██╗██╔════╝
   ██║   ██║     ██║   ██║██║  ██║█████╗
   ██║   ██║     ██║   ██║██║  ██║██╔══╝
   ██║   ╚██████╗╚██████╔╝██████╔╝███████╗
   ╚═╝    ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝  v{__version__}
```

Powered by the **Claude Agent SDK** — uses your Claude Code login (Pro/Max or `ANTHROPIC_API_KEY`).

- Tool calls prompt an **approve/deny** dialog (a / d).
- `/model` pick model · `/effort` reasoning effort · `/tools` pick tools · `/stats` panel · `/harvest` map session
- Click **model**, **effort**, or **system tools** in the stats panel to change them.
- Settings persist per project in `.textualcode.json`.
"""


class TextualCodeApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "request_quit", "Quit"),
        ("ctrl+t", "toggle_stats", "Stats"),
        ("ctrl+g", "toggle_workspace", "Workspace"),
        ("escape", "interrupt", "Interrupt"),
    ]

    # Compact density (tighter conversation spacing + borderless input/dialogs).
    # On by default; a future Settings page will flip this. init=False so it is
    # applied explicitly in on_mount (after the widgets exist) rather than during
    # early mount — see _apply_compact.
    compact: reactive[bool] = reactive(True, init=False)

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings or Settings()
        self._project_dir = Path.cwd()
        self._project = ProjectConfig.load(self._project_dir)
        self._model_label = self._project.model
        self._effort_label = self._project.effort
        self._modal = ModalBridge(self)
        self._agent = AgentSession(
            self._settings,
            permission_handler=self._modal.ask_permission,
            question_handler=self._modal.ask_question,
            model=self._project.model,
            tools=self._project.tools,
            effort=self._project.effort,
        )
        self._commands = CommandRouter()
        self._accountant = TurnAccountant()
        self._stats = self._accountant.stats  # alias — StatsView reads this directly
        self._transcript = Transcript()
        self._last_context: dict | None = None
        self._model_ctl = ModelController(self)
        self._effort_ctl = EffortController(self)
        self._tools_ctl = ToolsController(self)
        self._harvest_ctl = HarvestController(self)
        self._workspace_ctl = WorkspaceController(self)
        self._session = SessionController(self)
        self._quit = QuitGuard(self)
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
            yield WorkspacePanel(self._project_dir, id="workspace")
            yield ConversationView(id="conversation")
            with Vertical(id="sidebar"):
                yield StatsPanel(id="stats")
                yield TaskPanel(id="tasks")
        yield ThinkingBar(id="thinking")
        yield PromptInput(id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "TextualCode"
        self._status.set_phase("connecting…")
        self._conversation = self.query_one(ConversationView)
        self._stats_panel = self.query_one(StatsPanel)
        self._task_panel = self.query_one(TaskPanel)
        self._workspace = self.query_one(WorkspacePanel)
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
            on_stream_progress=self._on_stream_progress,
        )
        self._commands.register("model", self._model_ctl.apply)
        self._commands.register("effort", self._effort_ctl.parse_command)
        self._commands.register("stats", self._toggle_stats_command)
        self._commands.register("tools", self._tools_ctl.parse_command)
        self._commands.register("harvest", self._harvest_command)
        self._apply_compact(self.compact)
        await self._conversation.add_markdown(WELCOME)
        self.query_one(PromptInput).focus()
        self.connect_agent()

    def action_request_quit(self) -> None:
        """Claude-Code-style quit: the first Ctrl+C arms a short confirm window
        and shows a hint; a second Ctrl+C within the window actually exits.

        This keeps a stray Ctrl+C (e.g. a terminal copy) from killing the app.
        """
        self._quit.request()

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

    def action_toggle_workspace(self) -> None:
        """Ctrl+G: show/hide the left workspace panel (Files/Diff tabs).

        On-demand refresh: recompute the diff each time the panel is revealed
        so it's current without any background polling. Hidden by default
        (CSS ``display: none``)."""
        showing = not self._workspace.display
        self._workspace.display = showing
        if showing:
            self._workspace.refresh_diff()
        else:
            # Don't leave the conversation/sidebar hidden behind a closed panel.
            self._workspace.expanded = False

    def on_workspace_panel_expand_toggled(
        self, message: WorkspacePanel.ExpandToggled
    ) -> None:
        """Blow the workspace up to fill the tab (or restore it).

        When expanded, hide the conversation and sidebar so the panel (now
        ``width: 1fr`` via its ``.expanded`` class) takes the whole body row.
        """
        visible = not message.expanded
        self._conversation.display = visible
        self.query_one("#sidebar").display = visible

    def on_workspace_panel_review_requested(
        self, message: WorkspacePanel.ReviewRequested
    ) -> None:
        """Review button: run a code-review subagent over the working-tree diff."""
        self.review_diff()

    def on_workspace_panel_commit_requested(
        self, message: WorkspacePanel.CommitRequested
    ) -> None:
        """Commit button: draft a message with Haiku, stage all, and commit."""
        self.commit_diff()

    async def _toggle_stats_command(self, arg: str) -> None:
        self.action_toggle_stats()

    def watch_compact(self, compact: bool) -> None:
        """React to a compact change (e.g. from the future Settings page).
        init=False, so this never runs before on_mount applies the initial state."""
        self._apply_compact(compact)

    def _apply_compact(self, compact: bool) -> None:
        """Apply compact density to the conversation and prompt input."""
        self._conversation.set_class(compact, "compact")
        self.query_one(PromptInput).compact = compact

    async def _harvest_command(self, arg: str) -> None:
        self.harvest_now()

    def action_harvest(self) -> None:
        """Action target for the clickable '⟳ harvest' link in the stats panel."""
        self.harvest_now()

    def action_open_tools(self) -> None:
        """Action target for the clickable 'system tools' row in the panel."""
        self.open_tools_selector()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield from self._model_ctl.system_commands()
        yield from self._effort_ctl.system_commands()
        yield from self._tools_ctl.system_commands()

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

    def action_open_model(self) -> None:
        """Action target for the clickable 'model' row in the stats panel."""
        self.open_model_selector()

    def action_open_effort(self) -> None:
        """Action target for the clickable 'effort' row in the stats panel."""
        self.open_effort_selector()

    # -------------------------------------------------------------- workers --
    @work(exclusive=True, group=CONNECT)
    async def connect_agent(self) -> None:
        await self._session.connect()

    @work(exclusive=True, group=CONNECT)
    async def reconnect_agent(self) -> None:
        await self._session.reconnect()

    @work(exclusive=True, group=CONNECT)
    async def restart_session(self) -> None:
        """Free the context window: tear down the SDK client and start a fresh
        session (the supported reset — there's no in-process clear API yet).

        Also clears the local transcript and cached context fill so the next
        harvest reflects only the new session. The on-screen log is untouched.
        """
        await self._session.restart()

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

    def _on_stream_progress(self, message) -> None:
        """Update the stats panel mid-turn from a streamed assistant step.

        Only main-agent steps (parent_tool_use_id is None) carry the turn's own
        usage on this stream; subagent steps never reach it. The live tokens are
        a display-only preview — the authoritative total is committed when the
        ResultMessage arrives (see _on_turn_complete)."""
        if getattr(message, "parent_tool_use_id", None) is not None:
            return
        self._accountant.accrue_live_usage(getattr(message, "usage", None))
        self._stats_view.render()

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
        # Render now so the authoritative committed totals replace the live
        # preview immediately; refresh_context re-renders once context lands.
        self._stats_view.render()
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
            await self._model_ctl.apply(chosen)

    @work(exclusive=True, group=TOOLS_UI)
    async def open_effort_selector(self) -> None:
        """Open the RadioSet effort picker and apply the choice."""
        chosen = await self.push_screen_wait(
            EffortSelector(list(EFFORT_LEVELS), self._effort_label)
        )
        if chosen is not None:
            await self._effort_ctl.apply(chosen)

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
        self._tools_ctl.apply(tools)

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
        await self._harvest_ctl.run()

    @work(exclusive=True, group=REVIEW)
    async def review_diff(self) -> None:
        """Run the workspace Review action (isolated review subagent)."""
        await self._workspace_ctl.review()

    @work(exclusive=True, group=COMMIT)
    async def commit_diff(self) -> None:
        """Run the workspace Commit action (Haiku draft + git commit)."""
        await self._workspace_ctl.commit()

    @work(group=AGENT)
    async def _switch_model_worker(self, name: str) -> None:
        """Sync-callable wrapper for the command palette."""
        await self._model_ctl.apply(name)

    @work(group=AGENT)
    async def _switch_effort_worker(self, level: str) -> None:
        """Sync-callable wrapper for the command palette."""
        await self._effort_ctl.apply(level)

    async def on_unmount(self) -> None:
        try:
            await self._agent.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


def main() -> None:
    TextualCodeApp().run()


if __name__ == "__main__":
    main()
