# check-is_error-gate-writes

When adding resource caps or error signals to agent responses, ensure consuming code actually checks is_error before writes/commits/mutations, otherwise the cap is silent and the critical path remains open.

_Category: Security_
