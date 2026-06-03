"""Presentation widgets: the conversation container and the tool-call card."""

from __future__ import annotations

import json
import random
from pathlib import Path

from claude_agent_sdk import ToolUseBlock
from rich.console import Group
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static, TextArea

from .config import AGENT_ICON, USER_ICON
from .stats import UsageStats


class PromptInput(TextArea):
    """Auto-growing multiline prompt box.

    Built on `TextArea` so long text soft-wraps and the box grows with its
    content (up to `MAX_LINES`, then it scrolls). Enter submits; Shift+Enter /
    Ctrl+J insert a newline. A pasted/dropped file path is cleaned, inserted,
    and announced via `FileDropped`.
    """

    MIN_LINES = 1
    MAX_LINES = 10
    _BORDER_ROWS = 2  # TextArea default `border: tall` (top + bottom)

    class FileDropped(Message):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, placeholder: str = "", id: str | None = None) -> None:
        super().__init__(
            soft_wrap=True, tab_behavior="focus", placeholder=placeholder, id=id
        )

    # `value` shim so call sites keep working like the old single-line Input.
    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, new: str) -> None:
        self.text = new

    def on_mount(self) -> None:
        self._auto_resize()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._auto_resize()

    def _auto_resize(self) -> None:
        """Grow/shrink height to fit the wrapped content, clamped to a range."""
        rows = self.wrapped_document.height or 1
        rows = max(self.MIN_LINES, min(self.MAX_LINES, rows))
        # box-sizing is border-box, so add the border rows back on.
        self.styles.height = rows + self._BORDER_ROWS

    async def _on_key(self, event: events.Key) -> None:
        # Enter submits; Shift+Enter / Ctrl+J insert a newline. Textual also
        # dispatches this event to the base `TextArea._on_key` via the MRO
        # (MessagePump._get_dispatch_methods), and `event.stop()` only halts
        # bubbling — so we must `prevent_default()` to suppress the base newline
        # insert. For other keys we return without preventing, letting the base
        # handler run normally via that MRO dispatch.
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self.text))
            return
        if event.key in ("shift+enter", "ctrl+j"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

    def _on_paste(self, event: events.Paste) -> None:
        # Same MRO/prevent_default discipline as _on_key: only prevent_default()
        # stops the base `TextArea._on_paste` from also inserting the text.
        text = event.text
        if text:
            first = text.splitlines()[0].strip().strip('"').strip("'").strip()
            if first and Path(first).is_file():
                self.insert(first)
                self.post_message(self.FileDropped(first))
                event.prevent_default()  # suppress base TextArea._on_paste
                event.stop()
                return
        # Not a file path: let the base TextArea._on_paste run via MRO dispatch.


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
        self._turn_active = False  # True while animating a turn (vs. idle/notice)
        self._fixed_label = None   # pinned word (e.g. "Harvesting") vs. rotating gerunds

    def on_mount(self) -> None:
        self.display = False

    @property
    def active(self) -> bool:
        """True while a turn is animating (the agent is working/thinking)."""
        return self._turn_active

    def show_notice(self, text: str) -> bool:
        """Show a transient one-line notice (e.g. the quit hint) when idle.

        Returns False if the bar is busy animating a turn, so the caller can
        fall back to another surface (e.g. a toast).
        """
        if self._turn_active:
            return False
        self.update(text)
        self.display = True
        return True

    def clear_notice(self) -> None:
        """Hide a notice, unless a turn started animating in the meantime."""
        if not self._turn_active:
            self.display = False

    def start(self, label: str | None = None) -> None:
        """Begin the animation. With `label` (e.g. "Harvesting") the word is
        pinned and shown as a task indicator; without it, gerunds rotate."""
        self._ticks = self._elapsed = self._tokens = 0
        self._fixed_label = label
        self._gerund = label or random.choice(_GERUNDS)
        self._turn_active = True
        self.display = True
        if self._timer is None:
            self._timer = self.set_interval(0.2, self._tick)
        else:
            self._timer.resume()
        self._refresh()

    def stop(self) -> None:
        self._turn_active = False
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
        if self._ticks % 25 == 0 and self._fixed_label is None:
            self._gerund = random.choice(_GERUNDS)
        self._refresh()

    def _refresh(self) -> None:
        tok = f" · ↓ {self._tokens} tokens" if self._tokens else ""
        mode = "thinking" if self._fixed_label is None else "working"
        self.update(
            f"[orange1]{_STARS[self._frame]} {self._gerund}…[/orange1] "
            f"[dim]({self._elapsed}s{tok} · {mode})[/dim]"
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
    _BAR_CELLS = 24

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

    @staticmethod
    def _grid() -> Table:
        """A two-column label/value grid; values flush to the right border.

        `expand=True` stretches every section grid to the full panel width, so
        the right-justified value column lands on the same right edge in every
        section — values line up across tokens / cost / context.
        """
        g = Table.grid(expand=True, padding=(0, 1))
        g.add_column(justify="left", ratio=1, no_wrap=True, overflow="ellipsis")
        g.add_column(justify="right", no_wrap=True)
        return g

    @staticmethod
    def _rule(markup: str) -> Rule:
        """A left-aligned section divider; headline numbers ride in the title."""
        return Rule(Text.from_markup(markup), align="left", characters="─", style="grey37")

    @classmethod
    def _bar(cls, pct: float, color: str) -> Text:
        """Full-width gauge: a solid colored fill over a dim solid track.

        A solid track (rather than light-shade ░) reads as one continuous bar
        even at low fill, instead of dithered noise. Any non-zero fill shows at
        least one cell so a tiny percentage is still visible.
        """
        filled = round(pct / 100 * cls._BAR_CELLS)
        if pct > 0:
            filled = max(1, filled)
        filled = min(filled, cls._BAR_CELLS)
        empty = cls._BAR_CELLS - filled
        return Text.from_markup(
            f" [{color}]{'█' * filled}[/][grey30]{'█' * empty}[/grey30]"
        )

    def show(self, stats: UsageStats, model: str, context: dict | None = None) -> None:
        rate = stats.cache_hit_rate
        rcolor = self._rate_color(rate)

        head = self._grid()
        model_cell = Text(model, style=Style(meta={"@click": "app.open_model"}))
        model_cell.stylize("underline")
        head.add_row("[dim]model[/dim]", model_cell)
        head.add_row("[dim]turns[/dim]", f"[b]{stats.turns}[/b]")

        tok = self._grid()
        tok.add_row("input", f"{stats.input_tokens:,}")
        tok.add_row("output", f"{stats.output_tokens:,}")
        tok.add_row("cache write", f"{stats.cache_creation_tokens:,}")
        tok.add_row("cache read", f"{stats.cache_read_tokens:,}")
        tok.add_row("[dim]total in[/dim]", f"[dim]{stats.total_input:,}[/dim]")

        cost = self._grid()
        cost.add_row("main", f"${stats.main_cost_usd:.4f}")
        sub = f"${stats.subagent_cost_usd:.4f}"
        if stats.subagent_tokens:
            sub += f" [dim]({_short(stats.subagent_tokens)} tok)[/dim]"
        cost.add_row("subagents", sub)
        cost.add_row("[b]total[/b]", f"[b]${stats.cost_usd:.4f}[/b]")

        parts = [
            head,
            self._rule("[b]tokens[/b]"),
            tok,
            self._rule(f"[b]cache hit[/b]  [{rcolor}]{rate * 100:.0f}%[/]  [dim]≥80%[/dim]"),
            self._bar(rate * 100, rcolor),
            self._rule("[b]cost[/b]"),
            cost,
        ]
        if context:
            parts.extend(self._context_parts(context))
        self.update(Group(*parts))

    def _context_parts(self, context: dict) -> list:
        total = context.get("totalTokens", 0)
        maximum = context.get("maxTokens") or context.get("rawMaxTokens") or 0
        pct = float(context.get("percentage", 0.0))
        fill = self._fill_color(pct)

        # A context ≥60% full risks "context rot" (quality decays well before
        # the hard limit) — flag it next to the percentage as a nudge to harvest.
        warn = "  [yellow]↯ rot risk[/yellow]" if pct >= 60 else ""

        body = self._grid()
        body.add_row("[dim]window[/dim]", f"[dim]{_short(total)}/{_short(maximum)}[/dim]")
        for cat in context.get("categories", []):
            name = str(cat.get("name", "")).lower()
            if name.startswith("free"):
                continue
            tokens = _short(int(cat.get("tokens", 0)))
            if name.startswith("system tools"):
                # Clickable: opens the per-tool selector (see App.action_open_tools).
                # Drop the "system " prefix so the long "(deferred)" variant fits
                # on one line instead of wrapping into an underlined block.
                label = Text(name.replace("system ", ""), style=Style(meta={"@click": "app.open_tools"}))
                label.stylize("underline")
                body.add_row(label, tokens)
            else:
                body.add_row(name, tokens)

        # ⟳ harvest: clickable harvest trigger (see App.action_harvest).
        harvest = self._grid()
        harvest_label = Text("⟳ harvest", style=Style(meta={"@click": "app.harvest"}))
        harvest_label.stylize("underline")
        harvest.add_row(harvest_label, "")

        return [
            self._rule(f"[b]context[/b]  [{fill}]{pct:.0f}%[/]{warn}"),
            self._bar(pct, fill),
            body,
            harvest,
        ]


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


class ToolGroupCard(Collapsible):
    """One compact, expandable line standing in for a run of tool calls.

    Collapsed it reads `🔧 N tools called · Read, Glob, …`; expanded it reveals
    the individual `ToolCard`s. Tools stream in across messages, so cards are
    mounted into the group incrementally via `add_tool`.
    """

    def __init__(
        self,
        *,
        max_input_chars: int,
        preview_keys: tuple[str, ...],
    ) -> None:
        self._max_input_chars = max_input_chars
        self._preview_keys = preview_keys
        self._names: list[str] = []
        super().__init__(title="🔧 tools…", collapsed=True, classes="tool-group")

    def compose(self):
        # Same shape as Collapsible.compose, but we keep a handle on the
        # Contents container so add_tool can mount new cards into it after
        # mount (mounting onto the Collapsible itself would escape the
        # collapse toggle, which only hides the Contents child).
        yield self._title
        self._contents = self.Contents()
        with self._contents:
            yield from self._contents_list

    async def add_tool(self, block: ToolUseBlock) -> None:
        self._names.append(block.name)
        await self._contents.mount(
            ToolCard(
                block,
                max_input_chars=self._max_input_chars,
                preview_keys=self._preview_keys,
            )
        )
        self.title = self._summary()

    def _summary(self) -> str:
        n = len(self._names)
        noun = "tool" if n == 1 else "tools"
        names = ", ".join(self._names)
        if len(names) > 48:
            names = names[:47] + "…"
        return f"🔧 {n} {noun} called · {names}"
