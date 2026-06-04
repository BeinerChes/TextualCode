"""The scrollable conversation transcript container."""

from __future__ import annotations

from rich.markdown import Markdown as RichMarkdown
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from .config import AGENT_ICON, USER_ICON
from .selectable_static import SelectableStatic


class ConversationView(VerticalScroll):
    """A scrollable transcript. Each entry is a row with a numbered gutter."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._count = 0  # numbered messages so far

    async def add_message(self, role: str, markdown: str) -> None:
        """A numbered, role-marked message (▲ you / ▼ agent).

        Messages are immutable once mounted (the renderer adds each completed
        TextBlock in full — nothing updates a row in place), so we render the
        markdown ONCE into a single ``SelectableStatic`` instead of a
        ``Markdown`` widget. A ``Markdown`` widget explodes into ~18 child
        widgets per heavy message (heading/paragraph/code-block/list/items); a
        ``Static`` is one widget that caches its render — ~18x fewer widgets,
        which is what keeps long transcripts smooth on scroll. See
        ``avoid-heavy-reparsing-static-content``. ``SelectableStatic`` adds back
        text selection, which a plain ``Static(RichMarkdown)`` silently loses.
        """
        self._count += 1
        icon = USER_ICON if role == "user" else AGENT_ICON
        await self._mount_row(
            f"[dim]{self._count:>3}[/dim] {icon}",
            SelectableStatic(RichMarkdown(markdown)),
        )

    async def add_markdown(self, markdown: str, classes: str = "") -> None:
        """An unnumbered note (welcome, status, errors)."""
        await self._mount_row(
            "", SelectableStatic(RichMarkdown(markdown), classes=classes)
        )

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
