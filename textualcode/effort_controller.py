"""EffortController — owns the reasoning-effort selection feature.

Mirrors ModelController / ToolsController: holds the non-worker effort logic;
the @work open_effort_selector worker stays on the App (it needs
push_screen_wait / MessagePump) and delegates here via EffortController.apply().

Effort is a connect-time SDK option (ClaudeAgentOptions.effort) with no runtime
setter — the SDK exposes set_model / set_permission_mode but not set_effort
(verified against claude-agent-sdk==0.2.88, client.py). So, like the `tools`
knob, changing effort reconnects the agent (a fresh session).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Generator

from textual.app import SystemCommand

from .config import EFFORT_LEVELS, EFFORT_VALUES, effort_display

if TYPE_CHECKING:
    from .app import TextualCodeApp


class EffortController:
    """Owns the effort-selection and effort-command logic for TextualCodeApp."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    # --------------------------------------------------------------- actions --

    async def apply(self, level: str) -> None:
        """Persist and apply an effort level, then reconnect the agent.

        No argument opens the RadioSet picker; an unknown value prints usage.
        """
        name = (level or "").strip().lower()
        if not name:
            self._app.open_effort_selector()  # no arg → open the picker
            return
        if name not in EFFORT_VALUES:
            choices = " · ".join(EFFORT_VALUES)
            await self._app._conversation.add_markdown(
                f"> Usage: `/effort` (choose) · `/effort <{choices}>`."
            )
            return

        # Applying effort means reconnecting (no runtime setter), so don't act
        # before the first connect completes — mirrors ModelController.apply.
        if not self._app._agent.connected:
            await self._app._conversation.add_markdown(
                "> Agent not connected yet — try again in a moment."
            )
            return

        # No-op when the effort is unchanged: a reconnect would needlessly
        # discard the conversation (AgentSession.reconnect starts a fresh
        # session). Re-selecting the current level from the picker is benign.
        if name == self._app._project.effort:
            await self._app._conversation.add_markdown(
                f"> Effort already **{effort_display(name)}** — no change."
            )
            return

        # Effort is connect-time only, so changing it reconnects (an exclusive
        # CONNECT-group worker → aclose()). Firing that mid-turn would silently
        # abandon the live turn; refuse instead and tell the user why — see the
        # guard-exclusive-operations-against-cancellation lesson.
        if self._app._agent_turn_active:
            await self._app._conversation.add_markdown(
                "> A turn is already running — interrupt it (Esc) or wait for it "
                "to finish, then change the effort."
            )
            return

        self._app._project.effort = name
        self._app._project.save(self._app._project_dir)
        self._app._agent.effort = name
        self._app._effort_label = name
        self._app._stats_view.render()
        await self._app._conversation.add_markdown(
            f"> Effort → **{effort_display(name)}** · saved "
            "(reconnecting — conversation resets)."
        )
        self._app.reconnect_agent()

    async def parse_command(self, arg: str) -> None:
        """`/effort` opens the selector; `/effort <level>` applies it."""
        await self.apply(arg)

    # -------------------------------------------------------- palette entries --

    def system_commands(self) -> Generator[SystemCommand, None, None]:
        """Yield effort-related command-palette entries."""
        yield SystemCommand(
            "Effort: choose…",
            "Pick the agent reasoning effort (reconnects the agent)",
            self._app.open_effort_selector,
        )
        for level in EFFORT_LEVELS:
            yield SystemCommand(
                f"Effort: {level['label']}",
                str(level["description"]),
                partial(self._app._switch_effort_worker, str(level["value"])),
            )
