# avoid-heavy-widget-subtrees-static-content

For static rendered content in Textual, use Static(RichMarkdown) or Static(Syntax) instead of Textual's Markdown/Code widgets to collapse widget subtrees (~18× reduction per message), preventing scroll relayout jank; tradeoff is loss of interactivity (links, copy buttons).

_Category: UI_
