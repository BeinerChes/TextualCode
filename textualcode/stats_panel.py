"""The right-side live session-usage panel."""

from __future__ import annotations

from rich.console import Group
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from .config import effort_display
from .formatting import _short
from .stats import UsageStats


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

    def show(
        self,
        stats: UsageStats,
        model: str,
        context: dict | None = None,
        effort: str = "default",
    ) -> None:
        rate = stats.cache_hit_rate
        rcolor = self._rate_color(rate)

        head = self._grid()
        model_cell = Text(model, style=Style(meta={"@click": "app.open_model"}))
        model_cell.stylize("underline")
        head.add_row("[dim]model[/dim]", model_cell)
        # Clickable: opens the effort selector (see App.action_open_effort).
        effort_cell = Text(
            effort_display(effort), style=Style(meta={"@click": "app.open_effort"})
        )
        effort_cell.stylize("underline")
        head.add_row("[dim]effort[/dim]", effort_cell)
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
