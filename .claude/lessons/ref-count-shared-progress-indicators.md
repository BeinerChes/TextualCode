# ref-count-shared-progress-indicators

When independent concurrent operations (agent turn, review, harvest, commit) all control a shared busy/progress indicator, use reference counting keyed per operation (increment on start, decrement on stop, hide at zero) rather than boolean state, to prevent the first stop() from falsely clearing the indicator while others run.

_Category: Concurrency_
