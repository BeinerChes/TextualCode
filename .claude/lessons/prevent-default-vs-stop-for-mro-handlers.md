# prevent-default-vs-stop-for-mro-handlers

In Textual event handlers overriding _on_*, call event.prevent_default() to suppress inherited base-class handlers in the MRO chain; event.stop() only stops bubbling to parents and does not prevent sibling base-class handlers from executing.

_Category: Textual_
