"""The animated 'agent is working' indicator bar."""

from __future__ import annotations

import random

from textual.widgets import Static

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
