# idempotency-gates-on-state-commits

Use explicit idempotency flags (e.g., _committed) reset in the setup phase, not state-reconstruction guards, to prevent double-application of side effects like double-billing; guards like 'if flag: return' wrongly suppress post-interrupt paths.

_Category: Concurrency_
