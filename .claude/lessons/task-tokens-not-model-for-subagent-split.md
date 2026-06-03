# task-tokens-not-model-for-subagent-split

Discriminate main agent from subagent cost using Task-message token counts and parent_tool_use_id, not model ID, because a subagent can run the same model as the main agent and model_usage keys keyed by model alone cannot separate them.

_Category: Cost Tracking_
