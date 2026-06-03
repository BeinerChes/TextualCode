# no-first-class-per-subagent-cost-api

The Claude Agent SDK does not expose per-subagent cost granularity; implement splits via Task notification tokens combined with per-model model_usage, or accept that include_partial_messages with StreamEvent parent_tool_use_id yields raw deltas without cost data.

_Category: SDK Integration_
