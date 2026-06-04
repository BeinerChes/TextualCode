"""Layout regression: the conversation reserves a stable scrollbar gutter.

With the default ``scrollbar-gutter: auto`` the messages reflow narrower the
moment the vertical scrollbar appears. During rapid mounting/auto-scroll there
is a frame where the scrollbar is drawn before the messages have re-wrapped, so
their last characters get painted *under* the scrollbar. ``#conversation`` sets
``scrollbar-gutter: stable`` to keep the content width constant whether or not
the scrollbar is visible. This test pins that: a message rendered before the
scrollbar exists has the same width as one rendered after it appears.
"""

from __future__ import annotations

from pathlib import Path

import textualcode
from textualcode.app import TextualCodeApp
from textualcode.conversation import ConversationView
from textualcode.selectable_static import SelectableStatic


class _TestApp(TextualCodeApp):
    """Real app + real CSS, minus the live SDK connection."""

    CSS_PATH = str(Path(textualcode.__file__).parent / "app.tcss")

    def connect_agent(self) -> None:  # no network in tests
        return


async def test_message_width_constant_when_scrollbar_appears() -> None:
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        cv = app.query_one(ConversationView)

        await cv.add_message("agent", "short message")
        await pilot.pause()
        assert cv.show_vertical_scrollbar is False
        width_without_scrollbar = app.query(SelectableStatic).last().region.width

        # Overflow the viewport so the scrollbar appears.
        for _ in range(40):
            await cv.add_message(
                "agent",
                "a longer line of content used to force the vertical scrollbar",
            )
        await pilot.pause()
        assert cv.show_vertical_scrollbar is True
        width_with_scrollbar = app.query(SelectableStatic).first().region.width

    # Stable gutter -> identical width, so no message is ever laid out into the
    # columns the scrollbar occupies.
    assert width_without_scrollbar == width_with_scrollbar
    # And content stays left of the scrollbar (its right edge never crosses the
    # inner edge of the scroll region).
    inner_right = cv.region.right - cv.scrollbar_size_vertical
    for widget in app.query(SelectableStatic):
        assert widget.region.right <= inner_right
