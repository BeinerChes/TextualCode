# test-interrupted-state-separately

Behavior under interruption (Esc, cancel) often differs from normal flow; verify guards intended for normal paths don't wrongly suppress post-interrupt side effects (e.g., ResultMessage handling, dialog dismissal).

_Category: Testing_
