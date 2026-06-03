"""Live background-task cards and the panel that holds them."""

from __future__ import annotations

from rich.table import Table
from textual.containers import VerticalScroll
from textual.widgets import Static

from .formatting import _short

_AVATARS = ["(•‿•)", "(o_o)", "(>‿<)", "(^_^)", "(•_•)", "(¬‿¬)", "(*_*)", "(·_·)", "(ↁ_ↁ)"]
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_STATUS = {"completed": ("✓", "green"), "failed": ("✗", "red"), "stopped": ("■", "yellow")}


class TaskCard(Static):
    """A live card for one background task: avatar, status, usage, summary."""

    def __init__(self, task_id: str, description: str) -> None:
        super().__init__(classes="task-card")
        self.task_id = task_id
        self.description = description
        self.status = "running"
        self.usage: dict | None = None
        self.summary = ""
        self._avatar = _AVATARS[hash(task_id) % len(_AVATARS)]
        self._frame = 0

    def on_mount(self) -> None:
        self.update(self._build())

    @property
    def running(self) -> bool:
        return self.status == "running"

    def tick(self) -> None:
        if self.running:
            self._frame = (self._frame + 1) % len(_SPINNER)
            self.update(self._build())

    def set_progress(self, description: str, usage: dict | None) -> None:
        self.description = description or self.description
        self.usage = usage
        self.update(self._build())

    def finish(self, status: str, summary: str) -> None:
        self.status = status
        self.summary = summary
        self.remove_class("task-card")
        self.add_class(f"task-{status}")
        self.update(self._build())

    def _build(self) -> Table:
        if self.running:
            marker, color = _SPINNER[self._frame], "yellow"
        else:
            marker, color = _STATUS.get(self.status, ("?", "white"))
        desc = self.description[:22].replace("[", r"\[")
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_row(
            f"[cyan]{self._avatar}[/cyan] [bold]{desc}[/bold]  [{color}]{marker}[/{color}]"
        )
        if self.usage:
            secs = self.usage.get("duration_ms", 0) // 1000
            grid.add_row(
                f"[dim]{_short(self.usage.get('total_tokens', 0))} tok · "
                f"{self.usage.get('tool_uses', 0)} tools · {secs}s[/dim]"
            )
        if self.summary:
            summ = self.summary[:70].replace("[", r"\[")
            grid.add_row(f"[italic dim]{summ}[/italic dim]")
        return grid


class TaskPanel(VerticalScroll):
    """Right-side panel of live background-task cards (keyed by task_id)."""

    BORDER_TITLE = "⚙ tasks"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._cards: dict[str, TaskCard] = {}

    def on_mount(self) -> None:
        self.set_interval(0.15, self._tick)

    def _tick(self) -> None:
        for card in self._cards.values():
            card.tick()

    async def _ensure(self, key: str, description: str) -> TaskCard:
        """Get or create+mount the card for `key` (handles out-of-order events)."""
        card = self._cards.get(key)
        if card is None:
            card = TaskCard(key, description)
            self._cards[key] = card
            await self.mount(card)
            self.scroll_end(animate=False)
        return card

    async def start(self, key: str, description: str) -> None:
        await self._ensure(key, description)

    async def progress(self, key: str, description: str, usage: dict | None) -> None:
        card = await self._ensure(key, description)
        card.set_progress(description, usage)

    async def finish_task(self, task_id: str, status: str, summary: str) -> None:
        """Finish every card belonging to `task_id` (workflows emit one
        notification for all their sub-agent cards)."""
        matched = [c for k, c in self._cards.items() if k.split(":", 1)[0] == task_id]
        if not matched:
            matched = [await self._ensure(f"{task_id}:", summary or "(task)")]
        for card in matched:
            card.finish(status, summary)
