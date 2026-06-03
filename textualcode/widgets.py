"""Presentation widgets: the conversation container and the tool-call card."""

from __future__ import annotations

import json
import random
from pathlib import Path

from claude_agent_sdk import ToolUseBlock
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Markdown, Static

from .config import AGENT_ICON, USER_ICON
from .stats import UsageStats


class PromptInput(Input):
    """The prompt box, with drag-and-drop / pasted file-path handling.

    Terminals paste a (often quoted) file path when a file is dropped; this
    strips the quotes, inserts the clean path, and announces the drop.
    """

    class FileDropped(Message):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    def _on_paste(self, event: events.Paste) -> None:
        text = event.text
        if text:
            first = text.splitlines()[0].strip().strip('"').strip("'").strip()
            if first and Path(first).is_file():
                self.insert_text_at_cursor(first)
                self.post_message(self.FileDropped(first))
                event.stop()
                return
        super()._on_paste(event)


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


_GERUNDS = [
    "Thinking", "Pondering", "Cogitating", "Prestidigitating", "Ruminating",
    "Conjuring", "Percolating", "Marinating", "Noodling", "Finagling",
    "Scheming", "Computing", "Brewing", "Simmering", "Sautéing", "Vibing",
]
_STARS = "✶✸✹✺✻✼"


class ThinkingBar(Static):
    """Animated 'agent is working' indicator: star + gerund + elapsed (+ tokens).

    Shown from prompt-submit until the turn's ResultMessage. Local animation
    only — no token cost.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timer = None
        self._ticks = 0
        self._elapsed = 0
        self._frame = 0
        self._gerund = "Thinking"
        self._tokens = 0

    def on_mount(self) -> None:
        self.display = False

    def start(self) -> None:
        self._ticks = self._elapsed = self._tokens = 0
        self._gerund = random.choice(_GERUNDS)
        self.display = True
        if self._timer is None:
            self._timer = self.set_interval(0.2, self._tick)
        else:
            self._timer.resume()
        self._refresh()

    def stop(self) -> None:
        self.display = False
        if self._timer is not None:
            self._timer.pause()

    def add_tokens(self, n: int) -> None:
        self._tokens += n
        self._refresh()

    def _tick(self) -> None:
        self._ticks += 1
        self._frame = (self._frame + 1) % len(_STARS)
        if self._ticks % 5 == 0:
            self._elapsed += 1
        if self._ticks % 25 == 0:
            self._gerund = random.choice(_GERUNDS)
        self._refresh()

    def _refresh(self) -> None:
        tok = f" · ↓ {self._tokens} tokens" if self._tokens else ""
        self.update(
            f"[orange1]{_STARS[self._frame]} {self._gerund}…[/orange1] "
            f"[dim]({self._elapsed}s{tok} · thinking)[/dim]"
        )


def _short(n: int) -> str:
    """Compact token count: 1_703_00 -> '170.3k', 1_000_000 -> '1.0m'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


class StatsPanel(Static):
    """Right-side panel showing live session usage: tokens, cache hit, cost."""

    BORDER_TITLE = "📊 stats"
    _BAR_CELLS = 16

    @staticmethod
    def _rate_color(rate: float) -> str:
        if rate >= 0.80:
            return "green"
        if rate >= 0.50:
            return "yellow"
        return "red"

    @staticmethod
    def _fill_color(pct: float) -> str:
        """Context fill: low is good (lots of free space)."""
        if pct < 50:
            return "green"
        if pct < 80:
            return "yellow"
        return "red"

    def show(self, stats: UsageStats, model: str, context: dict | None = None) -> None:
        rate = stats.cache_hit_rate
        color = self._rate_color(rate)
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right")

        model_cell = Text(model, style=Style(meta={"@click": "app.open_model"}))
        model_cell.stylize("underline")
        grid.add_row("[dim]model[/dim]", model_cell)
        grid.add_row("[dim]turns[/dim]", str(stats.turns))
        grid.add_row("", "")
        grid.add_row("[b]tokens[/b]", "")
        grid.add_row("input", f"{stats.input_tokens:,}")
        grid.add_row("output", f"{stats.output_tokens:,}")
        grid.add_row("cache write", f"{stats.cache_creation_tokens:,}")
        grid.add_row("cache read", f"{stats.cache_read_tokens:,}")
        grid.add_row("total in", f"{stats.total_input:,}")
        grid.add_row("", "")
        grid.add_row("[b]cache hit[/b]", f"[{color}]{rate * 100:.0f}%[/{color}]")
        grid.add_row("[dim]target[/dim]", "[dim]≥80%[/dim]")
        grid.add_row("", "")
        grid.add_row("[b]cost[/b]", f"${stats.cost_usd:.4f}")

        if context:
            self._add_context(grid, context)
        self.update(grid)

    def _add_context(self, grid: Table, context: dict) -> None:
        total = context.get("totalTokens", 0)
        maximum = context.get("maxTokens") or context.get("rawMaxTokens") or 0
        pct = float(context.get("percentage", 0.0))
        fill = self._fill_color(pct)

        filled = round(pct / 100 * self._BAR_CELLS)
        bar = (
            f"[{fill}]" + "█" * filled + "[/]"
            + "[dim]" + "░" * (self._BAR_CELLS - filled) + "[/dim]"
        )

        grid.add_row("", "")
        grid.add_row("[b]context[/b]", f"[{fill}]{pct:.0f}%[/{fill}]")
        grid.add_row(bar, "")
        grid.add_row("[dim]window[/dim]", f"{_short(total)}/{_short(maximum)}")
        for cat in context.get("categories", []):
            name = str(cat.get("name", "")).lower()
            if name.startswith("free"):
                continue
            tokens = _short(int(cat.get("tokens", 0)))
            if name.startswith("system tools"):
                # Clickable: opens the per-tool selector (see App.action_open_tools).
                label = Text(name, style=Style(meta={"@click": "app.open_tools"}))
                label.stylize("underline")
                grid.add_row(label, tokens)
            else:
                grid.add_row(name, tokens)


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


def tool_preview(block: ToolUseBlock, keys: tuple[str, ...]) -> str:
    """A short, single-line summary of a tool call for the card title."""
    data = block.input if isinstance(block.input, dict) else {}
    for key in keys:
        value = data.get(key)
        if value:
            line = str(value).splitlines()[0]
            return f"· {line[:60]}" + ("…" if len(line) > 60 else "")
    return ""


def _format_input(data: object, limit: int) -> str:
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > limit:
        text = text[:limit] + "\n… (truncated)"
    return text


class ToolCard(Collapsible):
    """A collapsible card showing a tool call: preview title + pretty JSON."""

    def __init__(
        self,
        block: ToolUseBlock,
        *,
        max_input_chars: int,
        preview_keys: tuple[str, ...],
    ) -> None:
        body = _format_input(block.input, max_input_chars)
        title = f"🔧 {block.name}  {tool_preview(block, preview_keys)}".rstrip()
        super().__init__(
            Markdown(f"```json\n{body}\n```"),
            title=title,
            collapsed=True,
            classes="tool",
        )
