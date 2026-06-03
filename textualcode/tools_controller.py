"""ToolsController — owns the built-in-tools selection feature.

Holds the non-worker tools logic. The @work open_tools_selector worker stays
on the App (it needs push_screen_wait / MessagePump); it delegates here via
ToolsController.apply().
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Generator

from textual.app import SystemCommand

if TYPE_CHECKING:
    from .app import TextualCodeApp


class ToolsController:
    """Owns the tools-selection and tools-command logic for TextualCodeApp."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    # --------------------------------------------------------------- actions --

    def apply(self, tools: list[str] | None) -> None:
        """Persist and apply a tools selection, then reconnect the agent.

        Verbatim extraction from app._apply_tools — every code path preserved.
        """
        self._app._project.tools = tools
        self._app._project.save(self._app._project_dir)
        self._app._agent.tools = tools
        self._app.reconnect_agent()

    async def parse_command(self, arg: str) -> None:
        """`/tools` opens the selector; `/tools on|off` enables all / none.

        Verbatim extraction from app._tools_command — every user-visible string
        and code path preserved byte-for-byte.
        """
        choice = arg.strip().lower()
        if choice == "on":
            self.apply(None)
        elif choice == "off":
            self.apply([])
        elif not choice:
            self._app.open_tools_selector()
        else:
            await self._app._conversation.add_markdown(
                "> Usage: `/tools` (choose) · `/tools on` · `/tools off`."
            )

    # -------------------------------------------------------- palette entries --

    def system_commands(self) -> Generator[SystemCommand, None, None]:
        """Yield tools-related command-palette entries."""
        yield SystemCommand(
            "System tools: choose…",
            "Pick which built-in tools are enabled",
            self._app.open_tools_selector,
        )
        yield SystemCommand(
            "System tools: enable all",
            "Enable all built-in tools (reconnects the agent)",
            partial(self.apply, None),
        )
        yield SystemCommand(
            "System tools: disable all",
            "Disable all built-in tools (reconnects the agent)",
            partial(self.apply, []),
        )
