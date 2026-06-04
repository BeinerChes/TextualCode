"""Text-selection tests for ``SelectableStatic`` in conversation.py.

Background
----------
The render-perf migration swapped the Textual ``Markdown`` widget for
``Static(RichMarkdown(...))`` to collapse ~18 child widgets per message into
one. That silently broke text selection: ``Widget.get_selection`` only extracts
text when ``_render()`` yields a ``Text``/``Content``, but a Rich renderable is
wrapped in a ``RichVisual``, for which ``get_selection`` returns ``None``
(verified against Textual 8.2.7 source).

``SelectableStatic`` overrides ``get_selection`` to rebuild the text from the
strips ``Static`` already caches for display, so selection works again while
keeping the single-widget perf win.

These tests run a real (headless) Textual app so the widget actually renders to
strips — that is the only way ``_render_cache.lines`` is populated.
"""

from __future__ import annotations

from rich.markdown import Markdown as RichMarkdown
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from textual.widgets import Static

from textualcode.selectable_static import SelectableStatic


class _Harness(App):
    """Minimal app that mounts a single supplied widget."""

    def __init__(self, widget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


# ---------------------------------------------------------------------------
# 1. The fix: SelectableStatic extracts the full rendered text.
# ---------------------------------------------------------------------------

async def test_selectable_static_extracts_full_text() -> None:
    widget = SelectableStatic(RichMarkdown("Hello world"))
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        result = widget.get_selection(SELECT_ALL)

    assert result is not None
    extracted, ending = result
    assert "Hello world" in extracted
    assert ending == "\n"


# ---------------------------------------------------------------------------
# 2. The regression proof: a plain Static(RichMarkdown) is unselectable.
# ---------------------------------------------------------------------------

async def test_plain_static_richmarkdown_returns_none() -> None:
    """A plain Static wrapping a Rich renderable yields no selection text.

    This is exactly the behaviour that broke selection; SelectableStatic exists
    to fix it. If this assertion ever fails, upstream Textual changed and the
    subclass may no longer be necessary.
    """
    widget = Static(RichMarkdown("Hello world"))
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        assert widget.get_selection(SELECT_ALL) is None


# ---------------------------------------------------------------------------
# 3. Partial selection maps to rendered line/column coordinates.
# ---------------------------------------------------------------------------

async def test_selectable_static_partial_selection() -> None:
    widget = SelectableStatic(RichMarkdown("abcdefghij"))
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        full, _ = widget.get_selection(SELECT_ALL)
        lines = full.splitlines()
        content_line = next(ln for ln in lines if "abcdefghij" in ln)
        idx = lines.index(content_line)

        sel = Selection.from_offsets(Offset(0, idx), Offset(5, idx))
        extracted, _ = widget.get_selection(sel)

    assert extracted == content_line[:5]


# ---------------------------------------------------------------------------
# 4. Each line is rstrip-ed: copied text isn't padded out to the widget width.
# ---------------------------------------------------------------------------

async def test_selectable_static_strips_width_padding() -> None:
    widget = SelectableStatic(RichMarkdown("hi"))
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        extracted, _ = widget.get_selection(SELECT_ALL)

    assert "hi" in extracted
    # No line should carry trailing pad spaces out to the 40-col width.
    assert all(line == line.rstrip() for line in extracted.splitlines())


# ---------------------------------------------------------------------------
# 5. The real regression: a mouse DRAG must produce a sub-range selection, not
#    a whole-widget select-all. Before the offset-metadata fix, the compositor
#    could not resolve a content offset inside a RichVisual, so every drag fell
#    back to SELECT_ALL — you could only ever copy the entire message.
# ---------------------------------------------------------------------------

async def test_drag_produces_subrange_not_select_all() -> None:
    widget = SelectableStatic(RichMarkdown("abcdefghij"), id="s")
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        full, _ = widget.get_selection(SELECT_ALL)
        lines = full.splitlines()
        idx = next(i for i, ln in enumerate(lines) if "abcdefghij" in ln)
        col0 = lines[idx].index("abcdefghij")

        screen = widget.screen
        # Offset metadata must now be present so the compositor can hit-test a
        # cell inside the widget. This returned None before the fix.
        hit_widget, hit_offset = screen.get_widget_and_offset_at(col0 + 1, idx)
        assert hit_widget is widget
        assert hit_offset is not None

        await pilot.mouse_down("#s", offset=Offset(col0 + 1, idx))
        await pilot.hover("#s", offset=Offset(col0 + 4, idx))
        await pilot.mouse_up("#s", offset=Offset(col0 + 4, idx))
        await pilot.pause()

        sel = screen.selections.get(widget)
        assert sel is not None
        assert sel != SELECT_ALL  # the regression: drag used to select-all
        assert sel.start is not None and sel.end is not None
        text = screen.get_selected_text()

    assert text
    assert text in "abcdefghij"
    assert text != "abcdefghij"  # a proper sub-range, not the whole message


# ---------------------------------------------------------------------------
# 6. The selection highlight is painted by the widget itself, because
#    RichVisual ignores the selection handed to it via RenderOptions.
#
#    This asserts the highlight is actually VISIBLE — the selected cells get a
#    different background and the text colour survives. An earlier version only
#    checked `list(highlighted) != list(plain)`, which passed even though the
#    real bug left the colours unchanged: the selection style was applied as a
#    Rich *base* style (`style + segment.style`), so each segment's own fg/bg
#    won and the highlight never showed. It must be a *post_style* overlay.
# ---------------------------------------------------------------------------

def _bg_colors(strip) -> set:
    return {str(seg.style.bgcolor) for seg in strip if seg.style is not None}


async def test_selection_highlight_is_painted() -> None:
    widget = SelectableStatic(RichMarkdown("abcdefghij"), id="s")
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        full, _ = widget.get_selection(SELECT_ALL)
        lines = full.splitlines()
        idx = next(i for i, ln in enumerate(lines) if "abcdefghij" in ln)

        plain = widget.render_line(idx)
        base_bgs = _bg_colors(plain)

        widget.screen.selections = {
            widget: Selection.from_offsets(Offset(0, idx), Offset(4, idx))
        }
        await pilot.pause()
        highlighted = widget.render_line(idx)

    # Same characters rendered...
    assert highlighted.text == plain.text
    # ...but a NEW background colour now appears (the selection tint), proving
    # the highlight is visible rather than a no-op style merge.
    highlight_bgs = _bg_colors(highlighted)
    new_bgs = highlight_bgs - base_bgs
    assert new_bgs, "selection added no new background colour — highlight invisible"
    # The selected sub-range must contain at least two backgrounds (tinted +
    # untinted), i.e. only part of the line is highlighted.
    assert len(highlight_bgs) >= 2
    # Text colour is preserved (transparent selection foreground keeps it).
    fg_colors = {str(seg.style.color) for seg in highlighted if seg.style and seg.text.strip()}
    assert "None" not in fg_colors  # every visible glyph still has a real colour


# ---------------------------------------------------------------------------
# 7. End-to-end: a real mouse DRAG must produce a VISIBLE highlight on the
#    rendered line — selection state -> widget refresh -> render_line repaint.
#    This is the exact path that failed live ("no highlight at all") while the
#    selection state itself was correct.
# ---------------------------------------------------------------------------

async def test_drag_paints_visible_highlight() -> None:
    widget = SelectableStatic(RichMarkdown("abcdefghij"), id="s")
    async with _Harness(widget).run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        full, _ = widget.get_selection(SELECT_ALL)
        lines = full.splitlines()
        idx = next(i for i, ln in enumerate(lines) if "abcdefghij" in ln)
        col0 = lines[idx].index("abcdefghij")

        base_bgs = _bg_colors(widget.render_line(idx))

        await pilot.mouse_down("#s", offset=Offset(col0, idx))
        await pilot.hover("#s", offset=Offset(col0 + 5, idx))
        await pilot.mouse_up("#s", offset=Offset(col0 + 5, idx))
        await pilot.pause()

        after = widget.render_line(idx)

    assert _bg_colors(after) - base_bgs, "drag produced no visible highlight"


# ---------------------------------------------------------------------------
# 8. A selection spanning MULTIPLE rendered (wrapped) lines highlights each
#    line correctly (first line from start, middle lines fully, last line up to
#    the end offset) and copies the cross-line text. Exercises the `end == -1`
#    ("to end of line") branch of get_span that single-line tests never reach.
# ---------------------------------------------------------------------------

async def test_multiline_selection_highlights_and_copies() -> None:
    # Long text wraps to several lines in a narrow widget.
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    widget = SelectableStatic(RichMarkdown(text), id="s")
    async with _Harness(widget).run_test(size=(20, 12)) as pilot:
        await pilot.pause()
        full, _ = widget.get_selection(SELECT_ALL)
        lines = full.splitlines()
        # Find the first content line and ensure there are at least two.
        first = next(i for i, ln in enumerate(lines) if ln.strip())
        assert len([ln for ln in lines if ln.strip()]) >= 2, "text did not wrap"
        last = first + 1

        base_first = _bg_colors(widget.render_line(first))
        base_last = _bg_colors(widget.render_line(last))

        # Select from char 2 of the first line through char 3 of the next line.
        sel = Selection.from_offsets(Offset(2, first), Offset(3, last))
        widget.screen.selections = {widget: sel}
        await pilot.pause()

        # Both lines are repainted with the highlight tint.
        assert _bg_colors(widget.render_line(first)) - base_first
        assert _bg_colors(widget.render_line(last)) - base_last

        extracted, _ = widget.get_selection(sel)

    # Copied text spans the line break and respects the start/end offsets.
    assert "\n" in extracted
    assert extracted.splitlines()[0] == lines[first][2:]
    assert extracted.splitlines()[-1] == lines[last][:3]
