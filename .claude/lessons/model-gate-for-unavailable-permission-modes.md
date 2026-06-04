# model-gate-for-unavailable-permission-modes

For permission modes with model or account gates (e.g., auto mode requires Opus 4.6+/Sonnet 4.6 or Team/Enterprise enablement), implement a client-side model-version heuristic gate before offering the mode, because set_permission_mode() control responses do not confirm active mode and unavailable mo

_Category: Permissions_
