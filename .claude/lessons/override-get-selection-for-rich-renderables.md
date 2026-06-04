# override-get-selection-for-rich-renderables

Override Static.get_selection() to extract text from _render_cache.lines when wrapping Rich renderables, since Textual only auto-extracts from Text/Content objects, not RichVisual.

_Category: UI_
