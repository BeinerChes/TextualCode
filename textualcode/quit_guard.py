"""QuitGuard: two-step Ctrl+C confirmation with a timed disarm window.

Extracted from ``TextualCodeApp.action_request_quit`` / ``_disarm_quit`` so
that ``app.py`` carries only the thin action shim.  Every user-visible string
is byte-identical to the original.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import TextualCodeApp


class QuitGuard:
    """Arms a ~3-second confirm window on the first Ctrl+C; exits on the second.

    Lesson ``two-step-quit-with-confirm-window``: implement destructive actions
    as two-step confirms with a ~3 s timeout so a stray Ctrl+C never kills the
    app.
    """

    # Window (seconds) during which a second Ctrl+C confirms quit.
    _QUIT_WINDOW = 3.0

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app
        self._armed = False
        self._timer = None

    def request(self, on_confirm=None) -> None:
        """Handle a quit request (verbatim extraction from action_request_quit).

        Parameters
        ----------
        on_confirm:
            Optional callable invoked when the second Ctrl+C fires.  Defaults
            to ``self._app.exit()`` so the call site in app.py can pass nothing
            and retain identical behaviour.
        """
        if self._armed:
            if on_confirm is not None:
                on_confirm()
            else:
                self._app.exit()
            return
        self._armed = True
        if not self._app._thinking.show_notice(
            "[yellow]Press Ctrl+C again to exit[/yellow]"
        ):
            # ThinkingBar is busy animating — fall back to a toast.
            self._app.notify(
                "Press Ctrl+C again to exit",
                severity="warning",
                timeout=self._QUIT_WINDOW,
            )
        self._timer = self._app.set_timer(self._QUIT_WINDOW, self._disarm)

    def _disarm(self) -> None:
        self._armed = False
        self._timer = None
        self._app._thinking.clear_notice()
