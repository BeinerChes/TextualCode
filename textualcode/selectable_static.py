"""``SelectableStatic`` — a ``Static`` that stays fully text-selectable when its
content is a Rich renderable (e.g. ``rich.markdown.Markdown``).

Why this exists
---------------
Rendering a message as ``Static(RichMarkdown(...))`` instead of Textual's
``Markdown`` widget collapses ~18 child widgets per message into one, which is
what keeps long transcripts smooth on scroll. But a Rich renderable is rendered
through ``RichVisual.render_strips`` (Textual 8.2.7), which — unlike Textual's
native ``Content`` visual — does two things that break selection:

1. It never stamps per-cell *offset metadata* onto the rendered strips. The
   compositor (``Compositor.get_widget_and_offset_at``) reads that metadata to
   map a mouse cell to a content ``(column, row)`` offset. With no metadata it
   returns ``None``, so ``SelectState.is_single_content_widget`` is false and
   Textual falls back to selecting the *whole* widget (``SELECT_ALL``) — you can
   never drag-select part of a message.
2. It ignores the ``selection``/``selection_style`` handed to it via
   ``RenderOptions``, so even a whole-widget selection is never *highlighted*.

``SelectableStatic`` restores both, mirroring what ``Content`` does natively:

- ``render_line`` stamps offset metadata via ``Strip.apply_offsets`` (so the
  compositor can build a real sub-widget range selection), and paints the
  ``screen--selection`` highlight onto the selected cell range itself.
- ``get_selection`` rebuilds the text from the strips ``Static`` already caches
  for display (``_render_cache.lines``). Those strips are exactly what is
  painted, so the selection offsets — which index rendered line/column
  positions — line up, wrapping included. Each line is ``rstrip``-ed so copied
  text isn't padded out to the widget width.

All offsets are kept in a single, self-consistent coordinate space: one rendered
(already-wrapped) strip == one "line", indexed by its position in the render
cache, with ``x`` counting characters into that strip. ``apply_offsets``,
``Selection.get_span`` (highlight) and ``Selection.extract`` (copy) therefore
all agree.

Verified against Textual 8.2.7 source (``visual.py``, ``content.py``,
``strip.py``, ``_compositor.py``, ``selection.py``).
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.widgets import Static


class SelectableStatic(Static):
    """A ``Static`` whose Rich-renderable content stays selectable."""

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        if self._dirty_regions:
            self._render_content()
        lines = self._render_cache.lines
        if not lines:
            return None
        text = "\n".join(strip.text.rstrip() for strip in lines)
        return selection.extract(text), "\n"

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        # Paint the selection highlight FIRST (RichVisual won't), then stamp the
        # per-cell offset metadata LAST: apply_offsets walks the segments left to
        # right assigning sequential offsets, so it stays correct even after the
        # highlight has split a segment in two. The compositor reads that
        # metadata to map a mouse cell to a content offset, which is what lets
        # Textual build a sub-widget range selection instead of select-all.
        selection = self.text_selection
        if selection is not None:
            strip = self._apply_selection(strip, y, selection)
        return strip.apply_offsets(0, y)

    def _apply_selection(self, strip: Strip, y: int, selection: Selection) -> Strip:
        """Paint the ``screen--selection`` highlight onto the selected range of
        line ``y``, replicating what Textual's ``Content`` visual does."""
        span = selection.get_span(y)
        if span is None:
            return strip
        start, end = span
        text = strip.text
        if end == -1:  # -1 means "to the end of the line"
            end = len(text)
        start = max(0, min(start, len(text)))
        end = max(start, min(end, len(text)))
        if start == end:
            return strip
        # Selection offsets count characters; Strip.divide cuts by cells. Map
        # character offsets to cell offsets so wide glyphs highlight correctly.
        start_cell = cell_len(text[:start])
        end_cell = cell_len(text[:end])
        if start_cell == end_cell:
            return strip
        post_style = self._selection_post_style()
        parts = strip.divide([start_cell, end_cell, strip.cell_length])
        before, middle, after = parts[0], parts[1], parts[2]
        # Overlay the selection style ON TOP of each selected segment's own
        # style. Segment.apply_style computes ``style + segment.style +
        # post_style``, so the highlight MUST go in ``post_style`` — passing it
        # as the base ``style`` (what Strip.apply_style does) loses to the
        # segment's existing fg/bg and the highlight silently never appears.
        highlighted = Strip(
            list(Segment.apply_style(list(middle), post_style=post_style)),
            middle.cell_length,
        )
        return Strip.join([before, highlighted, after])

    def _selection_post_style(self) -> RichStyle:
        """The ``screen--selection`` style, flattened and ready to overlay.

        ``screen--selection`` is themed as a *semi-transparent* background
        (``primary`` at 50%) over a *transparent* foreground. That shapes how it
        must be turned into a paintable Rich style:

        - Calling ``.rich_style`` on it directly flattens the alpha against
          nothing, collapsing it to a degenerate ``primary on primary`` — an
          invisible block where the text vanishes. Instead we blend it over the
          widget's own (opaque) ``visual_style``: the translucent background
          becomes a real, visible tint (e.g. ``#094472``) and the transparent
          foreground leaves each segment's own text colour untouched.
        - A transparent foreground (the default) means "keep the text colour",
          so we set only ``bgcolor`` and let per-segment colours (code spans,
          bold headers) show through the highlight. A theme that sets an
          explicit selection foreground is honoured.
        """
        selection_style = Style.from_styles(
            self.screen.get_component_styles("screen--selection")
        )
        flat = (self.visual_style + selection_style).rich_style
        foreground = selection_style.foreground
        if foreground is not None and foreground.a > 0:
            return RichStyle(color=flat.color, bgcolor=flat.bgcolor)
        return RichStyle(bgcolor=flat.bgcolor)
