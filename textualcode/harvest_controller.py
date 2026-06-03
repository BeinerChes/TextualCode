"""HarvestController: orchestrates the ⟳ harvest action.

Extracted from ``TextualCodeApp.harvest_now`` (the worker body) so that
``app.py`` carries only the thin ``@work`` shim.  Every user-visible string
is byte-identical to the original.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import report_error
from .harvest import Harvester
from .lessons import write_harvest
from .screens import ConfirmDialog

if TYPE_CHECKING:
    from .app import TextualCodeApp


class HarvestController:
    """Orchestrates a harvest: Haiku call → write files → confirm restart."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    async def run(self) -> None:
        """Body of the harvest_now worker (verbatim extraction from app.py)."""
        if self._app._transcript.empty:
            await self._app._conversation.add_markdown(
                "> Nothing to harvest yet — have a conversation first."
            )
            return
        await self._app._conversation.add_markdown(
            "> ⟳ Harvesting this session with Haiku…"
        )
        # Cold-starting an isolated Haiku client takes 15-30s with no streamed
        # output; show the animated bar so the harvest doesn't look frozen.
        self._app._thinking.start(label="Harvesting")
        try:
            result = await Harvester(model="haiku").run(
                self._app._transcript.render()
            )
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            self._app._thinking.stop()
            await report_error(
                self._app._conversation, "Harvest failed:", exc
            )
            return
        try:
            paths = write_harvest(self._app._project_dir, result)
        except Exception as exc:  # noqa: BLE001 - report write failures cleanly
            self._app._thinking.stop()
            await report_error(
                self._app._conversation,
                "Could not write harvest files:",
                exc,
            )
            return
        self._app._thinking.stop()
        cost = f" · ${result.cost:.4f}" if result.cost else ""
        added = len(paths.new_lessons)
        lessons_note = f", +{added} lesson(s)" if added else ""
        await self._app._conversation.add_markdown(
            f"> ✅ Harvested → `{paths.root.name}/state.md`{lessons_note}{cost}."
        )
        # Offer to free the context window by restarting the SDK session.  This
        # runs in a worker, so push_screen_wait is safe (unlike the SDK-callback
        # dialogs, which must use push_screen + Future).
        restart = await self._app.push_screen_wait(
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
            self._app.restart_session()
