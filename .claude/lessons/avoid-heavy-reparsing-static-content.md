# avoid-heavy-reparsing-static-content

Don't re-instantiate heavy parsing widgets like Markdown per item for static content; parse once with Static(Syntax(...)) to avoid quadratic re-parsing costs.

_Category: Performance_
