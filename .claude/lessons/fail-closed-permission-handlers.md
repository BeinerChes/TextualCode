# fail-closed-permission-handlers

Permission/authorization callbacks that cannot resolve a decision must return Deny (fail-closed), not Allow (fail-open), to prevent unintended privilege escalation when handlers are misconfigured or missing.

_Category: Security_
