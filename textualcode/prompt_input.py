"""The auto-growing multiline prompt input box."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.message import Message
from textual.widgets import TextArea


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
        # A file drop arrives here too: this terminal (and most others) delivers
        # a drag-and-drop as a bracketed `Paste` event carrying the file path,
        # identical to Ctrl+V — so handling paste covers both input channels.
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
