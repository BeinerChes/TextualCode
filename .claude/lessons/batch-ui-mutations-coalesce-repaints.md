# batch-ui-mutations-coalesce-repaints

Wrap multiple sequential widget mutations (remove + mount + refresh) in async with widget.batch() to coalesce into one atomic repaint, preventing visible flicker and redundant layout passes.

_Category: UI_
