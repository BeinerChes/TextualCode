"""SessionController: connect/reconnect/restart lifecycle for TextualCodeApp.

Extracted from ``TextualCodeApp`` so that ``app.py`` carries only the thin
``@work`` shims (which must live on a MessagePump).  Every user-visible string
is byte-identical to the original.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import report_error
from .groups import PUMP

if TYPE_CHECKING:
    from .app import TextualCodeApp


class SessionController:
    """Owns the agent connection/reconnection/restart state machine."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    # ---------------------------------------------------------------- helpers --

    def abandon_turn(self) -> None:
        """Reset turn UI when a reconnect/restart abandons an in-flight turn (bug #1)."""
        self._app._agent_turn_active = False
        self._app._thinking.stop()
        self._app._renderer.last_usage = None
        self._app._renderer.last_cost = None
        self._app._renderer.last_model_usage = None

    async def reconnect_and_rebind(self) -> None:
        """Abandon any in-flight turn, cancel the old pump, reconnect, start a fresh pump."""
        self.abandon_turn()
        self._app.workers.cancel_group(self._app, PUMP)   # sdk-03: stop the old pump before tearing down its client
        await self._app._agent.reconnect()
        self._app.read_agent_stream()

    # ------------------------------------------------------------- lifecycle --

    async def connect(self) -> None:
        """Body of the connect_agent worker (verbatim extraction from app.py)."""
        try:
            await self._app._agent.connect()
            self._app._model_ctl.refresh_models()
            self._app._status.set_phase()
            self._app.read_agent_stream()  # start reading the message stream
        except Exception as exc:  # noqa: BLE001 - surface startup failures
            self._app._status.set_phase("offline")
            await report_error(
                self._app._conversation, None, exc,
                message=(
                    f"> **Could not start the agent.** {type(exc).__name__}: {exc}\n>\n"
                    "> Make sure the Claude Code CLI is installed and logged in."
                ),
            )

    async def reconnect(self) -> None:
        """Body of the reconnect_agent worker (verbatim extraction from app.py)."""
        tools = self._app._agent.tools
        desc = "all" if tools is None else ("none" if not tools else f"{len(tools)} selected")
        self._app._status.set_phase("reconnecting…")
        try:
            await self.reconnect_and_rebind()
            self._app._status.set_phase()
            await self._app._conversation.add_markdown(
                f"> ↻ Reconnected · system tools: **{desc}** "
                "(new session — conversation reset)."
            )
        except Exception as exc:  # noqa: BLE001 - surface reconnect failures
            self._app._status.set_phase("offline")
            await report_error(self._app._conversation, "Reconnect failed:", exc)

    async def restart(self) -> None:
        """Body of the restart_session worker (verbatim extraction from app.py).

        Free the context window: tear down the SDK client and start a fresh
        session (the supported reset — there's no in-process clear API yet).

        Also clears the local transcript and cached context fill so the next
        harvest reflects only the new session. The on-screen log is untouched.
        """
        self._app._status.set_phase("restarting…")
        try:
            await self.reconnect_and_rebind()
            self._app._transcript.clear()
            self._app._last_context = None
            self._app._stats_view.render()
            self._app._status.set_phase()
            await self._app._conversation.add_markdown(
                "> ↻ **Session restarted** — context window cleared. The agent "
                "starts fresh; reference `state.md` to restore where we left off."
            )
        except Exception as exc:  # noqa: BLE001 - surface restart failures
            self._app._status.set_phase("offline")
            await report_error(self._app._conversation, "Restart failed:", exc)
