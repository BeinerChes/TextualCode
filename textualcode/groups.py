"""Worker-group name constants.

Centralises the literal strings used in ``@work(group=...)`` decorators so
that cancel/replace semantics are guaranteed to be consistent everywhere.
The values must never change — worker cancellation is keyed on exact string
equality, so renaming a constant is a behaviour change.
"""

# Connection lifecycle: connect / reconnect / restart run exclusively in this
# group so that starting a new connection cancels any in-flight one.
CONNECT = "connect"

# Long-lived SDK message-stream reader.  Only one pump runs at a time;
# reconnect cancels the old pump before binding to the new client.
PUMP = "pump"

# Agent turn: submit + interrupt share this group so an interrupt can cancel
# a hanging submit.
AGENT = "agent"

# Background interrupt worker — its own group so it does not cancel the pump.
INTERRUPT = "interrupt"

# Harvest orchestration — isolated from agent turns.
HARVEST = "harvest"

# Stats / context-usage refresh.
STATS = "stats"

# Modal selectors (model picker, tools picker) — one open at a time.
TOOLS_UI = "tools-ui"
