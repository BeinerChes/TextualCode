# textual-subprocess-threading

Always run subprocesses that may block (git, shell commands) in a Textual @work(thread=True) worker; never on the UI thread. Prevents UI stutter and unresponsiveness during long subprocess execution.

_Category: UI Threading_
