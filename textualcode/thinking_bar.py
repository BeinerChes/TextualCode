"""The 'agent is working' indicator bar.

The animation is Textual's built-in :class:`LoadingIndicator` (pulsing dots);
this widget wraps it with the elapsed/token/label suffix and the ref-counted
multi-operation bookkeeping the rest of the app relies on.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import LoadingIndicator, Static


class ThinkingBar(Horizontal):
    """'Agent is working' indicator: pulsing dots + elapsed (+ tokens / label).

    Shown from prompt-submit until the turn's ResultMessage. The dots are
    animated by Textual's :class:`LoadingIndicator` (no token cost); this widget
    only drives the elapsed-time / token counter and the idle notice surface.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timer = None
        self._ticks = 0
        self._elapsed = 0
        self._tokens = 0
        self._label = "thinking"
        # Keys of the operations currently animating. The bar is shared by
        # several *concurrent* workers (the agent turn, Review, Commit, harvest)
        # that live in separate worker groups, so a single boolean would let the
        # first worker to finish clear the bar while the others are still
        # running — a false "idle". Ref-count by key instead: the bar hides only
        # when the last operation stops, and stop(key) is idempotent (a key
        # stopped twice — e.g. interrupt then ResultMessage — is harmless).
        self._active: set[str] = set()
        self._fixed_label = None   # pinned word (e.g. "Harvesting") vs. "thinking"

    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="thinking-dots")
        yield Static(id="thinking-label")

    def on_mount(self) -> None:
        self._dots = self.query_one("#thinking-dots", LoadingIndicator)
        self._text = self.query_one("#thinking-label", Static)
        self.display = False

    @property
    def active(self) -> bool:
        """True while any operation is animating (something is working)."""
        return bool(self._active)

    def show_notice(self, text: str) -> bool:
        """Show a transient one-line notice (e.g. the quit hint) when idle.

        Returns False if the bar is busy animating, so the caller can fall back
        to another surface (e.g. a toast).
        """
        if self._active:
            return False
        self._dots.display = False
        self._text.update(text)
        self.display = True
        return True

    def clear_notice(self) -> None:
        """Hide a notice, unless an operation started animating in the meantime."""
        if not self._active:
            self.display = False

    def start(self, label: str | None = None, key: str = "agent") -> None:
        """Begin (or join) the animation for operation ``key``.

        With `label` (e.g. "Harvesting") the word is shown in the suffix as a
        task indicator; without it the suffix reads "thinking". Multiple keys can
        be active at once; the elapsed/token counters reset only when starting
        from idle so a second concurrent operation doesn't rewind the first one's
        timer."""
        fresh = not self._active
        self._active.add(key)
        if fresh:
            self._ticks = self._elapsed = self._tokens = 0
        if label is not None:
            self._fixed_label = label
        elif fresh:
            self._fixed_label = None
        self._dots.display = True
        self.display = True
        if self._timer is None:
            self._timer = self.set_interval(0.2, self._tick)
        else:
            self._timer.resume()
        self._refresh()

    def stop(self, key: str = "agent") -> None:
        """Stop operation ``key``; hide the bar only when none remain active."""
        self._active.discard(key)
        if self._active:
            return  # other operations still running — keep animating
        self.display = False
        if self._timer is not None:
            self._timer.pause()

    def add_tokens(self, n: int) -> None:
        self._tokens += n
        self._refresh()

    def _tick(self) -> None:
        self._ticks += 1
        if self._ticks % 5 == 0:
            self._elapsed += 1
            self._refresh()

    def _refresh(self) -> None:
        tok = f" · ↓ {self._tokens} tokens" if self._tokens else ""
        label = self._fixed_label if self._fixed_label is not None else "thinking"
        self._text.update(f"[dim]({self._elapsed}s{tok} · {label})[/dim]")
