# resource-cap-isolation-clients

Isolated client patterns (one-shot LLM invocations with untrusted input) must set max_turns, max_budget_usd, and disallowed_tools=[Bash,Write,Edit,NotebookEdit] to bound OWASP-LLM10 uncapped consumption and restrict dangerous actions.

_Category: Security_
