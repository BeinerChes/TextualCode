# split-bug-fixes-from-pure-refactors

Separate confirmed-bug fixes from pure-refactor extractions into different steps; do bugs first (statically verifiable), defer refactors (harder to verify without live testing) to prevent unverifiable behavior changes from masking unforeseen regressions.

_Category: Refactoring_
