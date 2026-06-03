"""StatusPresenter and StatsView — single owners of sub_title and stats-panel.

StatusPresenter is the ONLY writer of App.sub_title; call set_phase() from
every place that previously did ``self.sub_title = ...``.

StatsView is the ONLY caller of StatsPanel.show(); call render() from every
place that previously did ``self._stats_panel.show(...)``.

Both are constructed in App.__init__ and hold a reference to the App.
StatsView.render() must only be called after on_mount() has assigned
``self._stats_panel``; StatusPresenter.set_phase() is safe at any time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import TextualCodeApp


class StatusPresenter:
    """Single writer of ``App.sub_title``.

    Call ``set_phase(phase)`` with a transient string (e.g. ``"connecting…"``)
    to show a transient sub-title, or call ``set_phase()`` (no argument / None)
    to restore the steady-state ``"agent sdk · <model>"``.
    """

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    def set_phase(self, phase: str | None = None) -> None:
        """Set ``app.sub_title``.

        Parameters
        ----------
        phase:
            A transient string such as ``"connecting…"`` / ``"reconnecting…"``
            / ``"restarting…"`` / ``"offline"`` to display as-is, or ``None``
            (the default) to restore the steady-state
            ``"agent sdk · <model_label>"``.
        """
        if phase is None:
            self._app.sub_title = f"agent sdk · {self._app._model_label}"
        else:
            self._app.sub_title = phase


class StatsView:
    """Single caller of ``StatsPanel.show(...)``.

    Call ``render()`` to push the current ``(stats, model_label, last_context)``
    state into the stats panel.  Only call after ``on_mount`` has assigned
    ``self._stats_panel`` on the App.
    """

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    def render(self) -> None:
        """Push current app state to the stats panel.

        Uses ``display_stats`` (committed totals + the in-flight turn's live
        token preview) so tokens / cache hit rate update mid-turn. Equals the
        committed stats between turns, so all callers can use it unconditionally.
        """
        self._app._stats_panel.show(
            self._app._accountant.display_stats,
            self._app._model_label,
            self._app._last_context,
            self._app._effort_label,
        )
