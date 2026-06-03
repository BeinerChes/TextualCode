"""AgentSession: owns the Claude Agent SDK connection lifecycle.

Deliberately UI-agnostic — it knows nothing about Textual. It exposes connect /
send / set_model / aclose and streams raw SDK messages back to the caller, who
decides how to render them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    PermissionResultAllow,
    PermissionResultDeny,
)

from .config import Settings
from .permissions import Decision, PermissionPolicy

# Asks the UI to approve a tool call and returns the user's Decision.
PermissionHandler = Callable[[str, dict], Awaitable[Decision]]
# Renders an AskUserQuestion form; returns {question_text: answer(s)} or None.
QuestionHandler = Callable[[list[dict]], Awaitable[dict | None]]


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
    ) -> None:
        self._settings = settings
        self._permission_handler = permission_handler
        self._question_handler = question_handler
        self._policy = PermissionPolicy()
        self._client: ClaudeSDKClient | None = None
        self._models: list[dict] = []
        self.model = model      # CLI value ("sonnet"/"haiku"/"default"/raw id) or None
        self.tools = tools      # None = all built-ins; [] = none; subset = list

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        options = ClaudeAgentOptions(
            system_prompt=self._settings.system_prompt,
            model=self._normalize_model(self.model),
            # None = full built-in set; [] = none; [names] = exactly those.
            tools=self.tools,
            strict_mcp_config=True,  # don't pull in ambient project/global MCP servers
            setting_sources=[],      # ignore ~/.claude & project settings, incl. their
                                     # permissions.allow rules — our dialog is authoritative
            can_use_tool=self._approve_tool,
        )
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._client = client
        info = await client.get_server_info()
        self._models = list(info.get("models", [])) if info else []

    @staticmethod
    def _normalize_model(model: str | None) -> str | None:
        """`"default"`/None both mean "let the CLI pick its recommended model"."""
        return None if model in (None, "default") else model

    def available_models(self) -> list[dict]:
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

    async def context_usage(self) -> dict | None:
        """Current context-window breakdown (the data behind `/context`)."""
        if self._client is None:
            return None
        try:
            return await self._client.get_context_usage()
        except Exception:  # noqa: BLE001 - degrade gracefully if unsupported
            return None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    def _require_client(self) -> ClaudeSDKClient:
        if self._client is None:
            raise RuntimeError("Agent is not connected")
        return self._client

    async def _approve_tool(self, tool_name, tool_input, context):
        """Tiered policy: auto-allow safe/remembered calls, else ask the UI."""
        if tool_name == "AskUserQuestion":
            return await self._answer_question(tool_input)
        if self._policy.auto_allow(tool_name, tool_input):
            return PermissionResultAllow()
        if self._permission_handler is None:
            return PermissionResultAllow()
        decision = await self._permission_handler(tool_name, tool_input)
        if decision.remember:
            self._policy.remember(tool_name, tool_input)
        if decision.allow:
            return PermissionResultAllow()
        return PermissionResultDeny(message="Denied by user.")

    async def _answer_question(self, tool_input: dict):
        """Render Claude's AskUserQuestion and return the answers as the result.

        Answers go back via `updated_input`: {questions, answers} where answers
        maps each question's text to the chosen option label(s).
        """
        questions = tool_input.get("questions", [])
        if self._question_handler is None:
            return PermissionResultAllow()  # no UI: let it proceed unanswered
        answers = await self._question_handler(questions)
        if answers is None:
            return PermissionResultDeny(message="User dismissed the question.")
        return PermissionResultAllow(
            updated_input={"questions": questions, "answers": answers}
        )
