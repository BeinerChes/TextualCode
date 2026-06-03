"""McpController — owns the MCP-server enable/disable feature.

Two layers:

- A per-project **trust gate** (`mcp_enabled`): whether ambient project/user MCP
  servers load at all. This is the security boundary — loading spawns stdio
  servers as subprocesses at connect, so it is opt-in per project. Toggling it
  reconnects (strict_mcp_config is connect-time only), like the effort knob.
- Per-server **enable/disable** once trusted: a *runtime* SDK operation
  (client.toggle_mcp_server) that does NOT reconnect, so the conversation is
  preserved. Change-detection reads LIVE status (not the persisted wishlist) so
  the panel/selector never diverge from reality.

The @work workers (open_mcp_selector, reconnect_agent) stay on the App; this
holds the non-worker logic they delegate to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generator

from textual.app import SystemCommand

from .errors import report_error

if TYPE_CHECKING:
    from .app import TextualCodeApp


class McpController:
    """Owns the MCP trust gate, per-server selection, and `/mcp` command."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    # --------------------------------------------------------- trust gate --

    async def set_project_enabled(self, enabled: bool) -> None:
        """Turn ambient MCP loading on/off for this project (reconnects).

        Mirrors EffortController.apply's guards: strict_mcp_config is a
        connect-time option, so flipping it discards the conversation — refuse
        mid-turn and no-op when unchanged.
        """
        if not self._app._agent.connected:
            await self._app._conversation.add_markdown(
                "> Agent not connected yet — try again in a moment."
            )
            return
        if enabled == self._app._agent.mcp_enabled:
            state = "enabled" if enabled else "disabled"
            await self._app._conversation.add_markdown(
                f"> MCP already **{state}** for this project — no change."
            )
            return
        if self._app._agent_turn_active:
            await self._app._conversation.add_markdown(
                "> A turn is already running — interrupt it (Esc) or wait for it "
                "to finish, then change MCP."
            )
            return

        self._app._project.mcp_enabled = enabled
        self._app._project.save(self._app._project_dir)
        self._app._agent.mcp_enabled = enabled
        if enabled:
            note = (
                "> 🔌 MCP **enabled** for this project · saved. Loading user + "
                "project servers (reconnecting — conversation resets)."
            )
        else:
            note = (
                "> 🔌 MCP **disabled** for this project · saved "
                "(reconnecting — conversation resets)."
            )
        await self._app._conversation.add_markdown(note)
        self._app.reconnect_agent()

    # ------------------------------------------------------- per-server --

    async def apply(self, enabled: list[str], servers: list[dict]) -> None:
        """Apply an enabled/disabled selection live and persist the intent.

        `enabled` is the set of server names the user wants ON; `servers` is the
        LIVE status list shown in the selector. Change-detection compares the
        wanted state against each server's actual `status` (not the persisted
        disabled set), so a drifted/failed toggle never makes a server
        un-toggleable. Persisted `disabled_mcp_servers` records the explicit
        intent (every server left OFF) for re-application on the next connect.
        """
        enabled_set = set(enabled)
        agent = self._app._agent
        changed: list[tuple[str, bool]] = []
        for server in servers:
            name = str(server.get("name", ""))
            live_enabled = server.get("status") != "disabled"
            want = name in enabled_set
            if want == live_enabled:
                continue
            try:
                await agent.set_mcp_enabled(name, want)
                changed.append((name, want))
            except Exception as exc:  # noqa: BLE001 - report per-server, keep going
                await report_error(
                    self._app._conversation, f"MCP toggle failed for {name}:", exc
                )

        # Persist explicit intent: every presented server the user left OFF.
        agent.disabled_mcp = {
            str(s.get("name", ""))
            for s in servers
            if str(s.get("name", "")) not in enabled_set
        }
        self._app._project.disabled_mcp_servers = sorted(agent.disabled_mcp)
        self._app._project.save(self._app._project_dir)
        self._app.refresh_mcp()  # re-read live status into the stats panel

        if changed:
            summary = " · ".join(
                f"{name} **{'on' if on else 'off'}**" for name, on in changed
            )
            await self._app._conversation.add_markdown(
                f"> 🔌 MCP servers: {summary} · saved."
            )

    # ------------------------------------------------------------ command --

    async def parse_command(self, arg: str) -> None:
        """`/mcp` opens the selector; `/mcp on|off` flips the project trust gate."""
        choice = arg.strip().lower()
        if choice == "on":
            await self.set_project_enabled(True)
        elif choice == "off":
            await self.set_project_enabled(False)
        elif not choice:
            self._app.open_mcp_selector()
        else:
            await self._app._conversation.add_markdown(
                "> Usage: `/mcp` (choose) · `/mcp on` · `/mcp off`."
            )

    # -------------------------------------------------------- palette entries --

    def system_commands(self) -> Generator[SystemCommand, None, None]:
        """Yield MCP-related command-palette entries."""
        yield SystemCommand(
            "MCP servers: choose…",
            "Enable MCP for this project, or toggle individual servers",
            self._app.open_mcp_selector,
        )
        yield SystemCommand(
            "MCP: enable for this project",
            "Load user + project MCP servers (reconnects the agent)",
            self._app._mcp_enable_worker,
        )
        yield SystemCommand(
            "MCP: disable for this project",
            "Stop loading ambient MCP servers (reconnects the agent)",
            self._app._mcp_disable_worker,
        )
