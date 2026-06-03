# separate-transient-from-canonical-state

Keep transient in-flight updates in a separate accumulator from committed canonical state; merge for display and discard transient at sync boundaries to prevent double-counting.

_Category: State Management_
