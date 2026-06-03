"""The scrollable conversation transcript container."""

from __future__ import annotations

from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from .config import AGENT_ICON, USER_ICON


class ConversationView(VerticalScroll):
    """A scrollable transcript. Each entry is a row with a numbered gutter."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._count = 0  # numbered messages so far

    async def add_message(self, role: str, markdown: str) -> None:
        """A numbered, role-marked message (▲ you / ▼ agent)."""
        self._count += 1
        icon = USER_ICON if role == "user" else AGENT_ICON
        await self._mount_row(f"[dim]{self._count:>3}[/dim] {icon}", Markdown(markdown))

    async def add_markdown(self, markdown: str, classes: str = "") -> None:
        """An unnumbered note (welcome, status, errors)."""
        await self._mount_row("", Markdown(markdown, classes=classes))

    async def add_widget(self, widget: Widget) -> None:
        """An unnumbered widget (e.g. a tool card)."""
        await self._mount_row("", widget)

    async def _mount_row(self, gutter: str, content: Widget) -> None:
        row = Horizontal(
            Static(gutter, classes="gutter"),
            content,
            classes="msg-row",
        )
        await self.mount(row)
        self.scroll_end(animate=False)
