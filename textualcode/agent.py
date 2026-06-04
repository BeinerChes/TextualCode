"""AgentSession: owns the Claude Agent SDK connection lifecycle.

Deliberately UI-agnostic — it knows nothing about Textual. It exposes connect /
send / set_model / aclose and streams raw SDK messages back to the caller, who
decides how to render them.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from .config import Settings
from .permissions import Decision, PermissionPolicy

log = logging.getLogger(__name__)

# Asks the UI to approve a tool call and returns the user's Decision.
PermissionHandler = Callable[[str, dict[str, Any]], Awaitable[Decision]]
# Renders an AskUserQuestion form; returns {question_text: answer(s)} or None.
QuestionHandler = Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any] | None]]


class AgentSession:
    """A thin, single-purpose wrapper around `ClaudeSDKClient`."""

    def __init__(
        self,
        settings: Settings,
        permission_handler: PermissionHandler | None = None,
        *,
        question_handler: QuestionHandler | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        effort: str | None = None,
        mcp_enabled: bool = False,
        disabled_mcp: list[str] | None = None,
    ) -> None:
        self._settings = settings
        self._permission_handler = permission_handler
        self._question_handler = question_handler
        self._policy = PermissionPolicy()
        self._client: ClaudeSDKClient | None = None
        self._models: list[dict[str, Any]] = []
        self.model = model      # CLI value ("sonnet"/"haiku"/"default"/raw id) or None
        # tools tri-state: None = all built-in tools; [] = no tools; [names] = that subset
        self.tools = tools
        self.effort = effort    # EffortLevel str, or "default"/None = let model decide
        # Per-project MCP trust gate. False → strict_mcp_config on → no ambient
        # MCP servers are loaded/spawned at connect (safe default).
        self.mcp_enabled = mcp_enabled
        # Server names the user has turned off (persisted intent); re-applied
        # after every connect via toggle_mcp_server (see _apply_disabled_mcp).
        self.disabled_mcp: set[str] = set(disabled_mcp or [])

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        options = ClaudeAgentOptions(
            system_prompt=self._settings.system_prompt,
            model=self._normalize_model(self.model),
            # Reasoning effort. Connect-time only — the SDK exposes set_model /
            # set_permission_mode but no set_effort (verified against
            # claude-agent-sdk==0.2.88, client.py), so changing it reconnects.
            # "default"/None → leave unset so the model decides.
            effort=self._normalize_effort(self.effort),
            # None = full built-in set; [] = none; [names] = exactly those.
            tools=self.tools,
            # Trust gate: strict (no ambient MCP) UNTIL the user enables MCP for
            # this project. With strict off, the CLI loads project `.mcp.json` +
            # user/global servers (setting_sources below makes them visible) and
            # SPAWNS stdio servers as subprocesses at connect — before any tool
            # gate — so loading is opt-in per project. Once enabled, individual
            # servers are turned off after connect (see _apply_disabled_mcp). The
            # isolated subagents (committer/reviewer/harvest) stay strict.
            strict_mcp_config=not self.mcp_enabled,
            # "user" + "project" load global + project settings — REQUIRED for the
            # SDK to inject CLAUDE.md as memory. Per the SDK's "what subagents
            # inherit" table, subagents pick up Project CLAUDE.md from this same
            # setting (Explore/Plan are the only built-ins that skip it).
            # Security trade-off: loading these sources also activates any
            # permissions.allow rules and hooks defined in user/project settings.
            # Those rules run BEFORE our can_use_tool dialog and can auto-approve
            # tool calls without user interaction. Users who place allow-all rules
            # in their global settings will bypass this app's permission gate.
            # The isolated subagents (committer/reviewer/harvest) use
            # setting_sources=[] to opt out of this entirely.
            setting_sources=["user", "project"],
            can_use_tool=self._approve_tool,
        )
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._client = client
        info = await client.get_server_info()
        self._models = list(info.get("models", [])) if info else []
        await self._apply_disabled_mcp()

    @staticmethod
    def _normalize_model(model: str | None) -> str | None:
        """`"default"`/None both mean "let the CLI pick its recommended model"."""
        return None if model in (None, "default") else model

    @staticmethod
    def _normalize_effort(effort: str | None) -> str | None:
        """`"default"`/None both mean "omit effort and let the model decide"."""
        return None if effort in (None, "default") else effort

    def available_models(self) -> list[dict[str, Any]]:
        """The model list reported by the connected CLI (value/displayName/desc)."""
        return self._models

    async def reconnect(self) -> None:
        """Apply connect-time options (e.g. the `tools` set) by reconnecting.

        Note: this starts a fresh session — in-memory conversation is reset.
        """
        await self.aclose()
        await self.connect()

    async def submit(self, prompt: str) -> None:
        """Send a prompt. Responses arrive on the `messages()` stream."""
        await self._require_client().query(prompt)

    async def interrupt(self) -> None:
        """Interrupt the in-flight turn (the Esc key, like Claude Code).

        Sends an interrupt signal to the CLI; the turn ends and a ResultMessage
        arrives on `messages()`. Streaming mode only (which is what we use).
        Non-destructive: the conversation/session is preserved.
        """
        await self._require_client().interrupt()

    async def messages(self) -> AsyncIterator[Message]:
        """Continuous stream of ALL session messages (responses + task events).

        Read by a single long-lived pump so background task progress is caught
        even between conversation turns.
        """
        async for message in self._require_client().receive_messages():
            yield message

    async def set_model(self, model: str | None) -> None:
        self.model = model
        await self._require_client().set_model(self._normalize_model(model))

    async def context_usage(self) -> dict[str, Any] | None:
        """Current context-window breakdown (the data behind `/context`)."""
        if self._client is None:
            return None
        try:
            return await self._client.get_context_usage()
        except Exception:  # noqa: BLE001 - degrade gracefully if unsupported
            log.debug("get_context_usage failed", exc_info=True)
            return None

    async def mcp_status(self) -> list[dict[str, Any]]:
        """Live status of every configured MCP server.

        Each entry has name / status (connected|pending|failed|needs-auth|
        disabled) / scope / tools / config. Empty list when not connected or if
        the CLI doesn't support the query. Verified against claude-agent-sdk
        ==0.2.88 (client.get_mcp_status -> {"mcpServers": [...]}).
        """
        if self._client is None:
            return []
        try:
            result = await self._client.get_mcp_status()
        except Exception:  # noqa: BLE001 - degrade gracefully if unsupported
            log.debug("get_mcp_status failed", exc_info=True)
            return []
        return list(result.get("mcpServers", [])) if result else []

    async def set_mcp_enabled(self, name: str, enabled: bool) -> None:
        """Enable/disable one MCP server live (no reconnect) and remember it.

        The SDK's toggle_mcp_server connects/disconnects the server and adds/
        removes its tools at runtime. We update `disabled_mcp` only after the
        toggle succeeds so persisted state matches reality; when offline we just
        record the intent for the next connect.
        """
        if self._client is not None:
            await self._client.toggle_mcp_server(name, enabled)
        if enabled:
            self.disabled_mcp.discard(name)
        else:
            self.disabled_mcp.add(name)

    async def _apply_disabled_mcp(self) -> None:
        """After connect, turn off every server the user has disabled.

        Toggles every name in `disabled_mcp` unconditionally (wrapped per-name)
        rather than only those already present in the status list: a slow stdio
        server may not have registered by the time we query, and we still want
        it off when it appears. An unknown/already-off name just no-ops or errors
        harmlessly.
        """
        if not self.mcp_enabled or not self.disabled_mcp or self._client is None:
            return
        for name in sorted(self.disabled_mcp):
            try:
                await self._client.toggle_mcp_server(name, False)
            except Exception:  # noqa: BLE001 - best effort; ignore unknown/failed names
                log.warning("toggle_mcp_server(%r, False) failed", name, exc_info=True)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    def _require_client(self) -> ClaudeSDKClient:
        if self._client is None:
            raise RuntimeError("Agent is not connected")
        return self._client

    async def _approve_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        _context: ToolPermissionContext,
    ) -> PermissionResult:
        """Tiered policy: auto-allow safe/remembered calls, else ask the UI."""
        if tool_name == "AskUserQuestion":
            return await self._answer_question(tool_input)
        if self._policy.auto_allow(tool_name, tool_input):
            return PermissionResultAllow()
        if self._permission_handler is None:
            return PermissionResultDeny(message="No permission handler configured.")
        decision = await self._permission_handler(tool_name, tool_input)
        if decision.remember:
            self._policy.remember(tool_name, tool_input)
        if decision.allow:
            return PermissionResultAllow()
        return PermissionResultDeny(message="Denied by user.")

    async def _answer_question(self, tool_input: dict[str, Any]) -> PermissionResult:
        """Render Claude's AskUserQuestion and return the answers as the result.

        Answers go back via `updated_input`: {questions, answers} where answers
        maps each question's text to the chosen option label(s).
        """
        questions = tool_input.get("questions", [])
        if self._question_handler is None:
            return PermissionResultDeny(message="No question handler configured.")
        answers = await self._question_handler(questions)
        if answers is None:
            return PermissionResultDeny(message="User dismissed the question.")
        return PermissionResultAllow(
            updated_input={"questions": questions, "answers": answers}
        )
