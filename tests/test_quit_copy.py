"""Ctrl+C = copy-when-selected, two-step-quit-otherwise.

The app binds Ctrl+C to ``action_request_quit`` at the App level, which
overrides Textual's built-in copy/quit handling. So "copy the selection instead
of arming quit" has to live in that action. These tests boot the real
``TextualCodeApp`` headlessly (with only the SDK connect stubbed out) and drive
the real action + widgets, matching the run_test style used elsewhere.
"""

from __future__ import annotations

from textual.selection import SELECT_ALL

from textualcode.app import TextualCodeApp
from textualcode.conversation import ConversationView
from textualcode.selectable_static import SelectableStatic


class _TestApp(TextualCodeApp):
    """Real app, minus the live SDK connection (irrelevant to Ctrl+C).

    ``CSS_PATH`` is cleared because it resolves relative to *this* module
    (tests/), not the package; styling is irrelevant to the copy/quit logic.
    """

    CSS_PATH = None

    def connect_agent(self) -> None:  # no network in tests
        # The real method is @work-wrapped and called without await in
        # on_mount; a plain no-op matches that call site without leaving an
        # un-awaited coroutine.
        return


# ---------------------------------------------------------------------------
# 1. With a selection, Ctrl+C copies it and does NOT arm quit.
# ---------------------------------------------------------------------------

async def test_ctrl_c_copies_selection_and_does_not_quit() -> None:
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.query_one(ConversationView).add_message("agent", "hello world")
        await pilot.pause()

        widget = app.query(SelectableStatic).last()
        app.screen.selections = {widget: SELECT_ALL}
        await pilot.pause()

        app.action_request_quit()
        await pilot.pause()

        assert "hello world" in app.clipboard          # copied
        assert app.screen.selections == {}             # selection cleared
        assert app._quit._armed is False               # quit NOT armed


# ---------------------------------------------------------------------------
# 2. With nothing selected, Ctrl+C arms the two-step quit (and copies nothing).
# ---------------------------------------------------------------------------

async def test_ctrl_c_arms_quit_when_no_selection() -> None:
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.query_one(ConversationView).add_message("agent", "hello world")
        await pilot.pause()

        assert app.screen.get_selected_text() is None  # nothing selected

        app.action_request_quit()
        await pilot.pause()

        assert app.clipboard == ""                     # nothing copied
        assert app._quit._armed is True                # quit armed


# ---------------------------------------------------------------------------
# 3. Copy, then a second Ctrl+C (now nothing selected) arms quit — i.e. copy
#    clears the selection so quit stays reachable.
# ---------------------------------------------------------------------------

async def test_second_ctrl_c_after_copy_arms_quit() -> None:
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await app.query_one(ConversationView).add_message("agent", "copy me")
        await pilot.pause()

        widget = app.query(SelectableStatic).last()
        app.screen.selections = {widget: SELECT_ALL}
        await pilot.pause()

        app.action_request_quit()  # copies, clears selection
        await pilot.pause()
        assert "copy me" in app.clipboard
        assert app._quit._armed is False

        app.action_request_quit()  # nothing selected now -> arms quit
        await pilot.pause()
        assert app._quit._armed is True
