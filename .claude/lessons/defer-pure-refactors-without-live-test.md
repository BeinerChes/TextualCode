# defer-pure-refactors-without-live-test

Pure refactors (moving code to new modules, no intended behavior change) are hard to verify without running the actual application; if you can't TUI-test, defer them until after behavior-changing work is landed and verified.

_Category: Risk Management_
