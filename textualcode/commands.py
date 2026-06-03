"""CommandRouter: parse and dispatch `/slash` commands.

Holds no app state — handlers are registered by whoever owns the behaviour, so
the router stays decoupled from the UI.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

Handler = Callable[[str], Awaitable[None]]


class UnknownCommand(Exception):
    """Raised when a `/command` has no registered handler."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class CommandRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler) -> None:
        self._handlers[name.lower()] = handler

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    async def dispatch(self, text: str) -> None:
        """Route `/name arg...` to its handler. Raises `UnknownCommand`."""
        parts = text[1:].split(maxsplit=1)
        name = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        handler = self._handlers.get(name)
        if handler is None:
            raise UnknownCommand(name)
        await handler(arg)
