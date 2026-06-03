"""ModalBridge: SDK-callback <-> Textual-modal bridge.

Moves the push_screen+Future plumbing that was in TextualCodeApp._ask_permission
and _ask_question into a single focused class so app.py stays thin.

WHY push_screen + Future (not push_screen_wait):
    The SDK calls ask_permission / ask_question from its own asyncio Task,
    not from a Textual @work worker. push_screen_wait is only safe when called
    from a Textual worker; from an external task the bridge must be a raw
    asyncio.Future created on get_running_loop() and resolved in the plain
    callback form of push_screen().
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .permissions import Decision, describe_key, similarity_key
from .screens import PermissionDialog, QuestionForm

if TYPE_CHECKING:
    from .app import TextualCodeApp


class ModalBridge:
    """Bridges SDK permission/question callbacks to Textual modal screens."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    async def ask_permission(self, tool_name: str, tool_input: dict) -> Decision:
        """Show the approve/deny modal and wait for the user's choice.

        Uses push_screen + a Future (not push_screen_wait) because the SDK calls
        this from its own task, not a Textual worker.
        """
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        label = describe_key(similarity_key(tool_name, tool_input))

        def _resolve(result: Decision | None) -> None:
            if not future.done():
                future.set_result(result or Decision(allow=False))

        self._app.push_screen(PermissionDialog(tool_name, tool_input, label), _resolve)
        return await future

    async def ask_question(self, questions: list[dict]) -> dict | None:
        """Show the AskUserQuestion form and return the answers (or None).

        Same push_screen + Future bridge as ask_permission (the SDK calls this
        from its own task, not a Textual worker).
        """
        future: asyncio.Future = asyncio.get_running_loop().create_future()

        def _resolve(result: dict | None) -> None:
            if not future.done():
                future.set_result(result)

        self._app.push_screen(QuestionForm(questions), _resolve)
        return await future
