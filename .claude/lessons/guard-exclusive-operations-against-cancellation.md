# guard-exclusive-operations-against-cancellation

Before triggering an exclusive operation (group=X), check if one is already active on that group and either refuse with a message or queue; do not silently cancel the running one, to prevent user confusion when a UI action unexpectedly interrupts in-flight work.

_Category: Async_
