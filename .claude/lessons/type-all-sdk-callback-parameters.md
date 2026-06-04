# type-all-sdk-callback-parameters

Permission callbacks and tool handlers in SDK usage must declare full parameter types exported by the SDK (e.g., CanUseTool, ToolPermissionContext), not bare/implicit, so type checkers verify the callback contract.

_Category: Typing_
