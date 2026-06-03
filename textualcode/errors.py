"""Error-reporting helpers for TextualCodeApp workers.

Collapses the repeated ``except Exception`` bodies (smell-01) into a single
async helper.  The two call shapes cover every site in app.py:

    # Most workers — label + type + message:
    await report_error(conversation, "Label", exc)

    # Sites that need a fully custom message (e.g. multi-line or no-type):
    await report_error(conversation, None, exc, message="> **Custom** text")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .widgets import ConversationView


async def report_error(
    conversation: "ConversationView",
    label: str | None,
    exc: BaseException,
    *,
    message: str | None = None,
) -> None:
    """Post a formatted error block to *conversation*.

    If *message* is given it is used verbatim; otherwise the block is built as::

        > **{label}** {type(exc).__name__}: {exc}

    This keeps every error site's visible output identical to the pre-refactor
    inline text while eliminating the copy-pasted boilerplate.
    """
    if message is None:
        text = f"> **{label}** {type(exc).__name__}: {exc}"
    else:
        text = message
    await conversation.add_markdown(text)
