"""Permission policy: tiered auto-allow + session memory by command similarity.

Modeled on Claude Code's own rules (deny > ask > allow, Bash prefix matching,
shell-operator awareness). Scope here is the *session* — remembered approvals
live in memory only, never persisted, so a broad rule can't outlive the run.
"""

from __future__ import annotations

from dataclasses import dataclass

# Safe, no-destructive-side-effect tools — auto-approved without a prompt.
AUTO_ALLOW_TOOLS = frozenset({"Read", "Glob", "Grep", "TodoWrite"})

# If a Bash command contains any of these, a remembered prefix must NOT match —
# e.g. an approved `git` rule must not green-light `git x && rm -rf /`.
_SHELL_OPERATORS = ("&&", "||", ";", "|", "`", "$(", ">", "<", "\n")


@dataclass(frozen=True)
class Decision:
    """Outcome of a permission request."""

    allow: bool
    remember: bool = False  # remember this call's similarity key for the session
    auto: bool = False      # switch the whole session into auto permission mode


def similarity_key(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """A coarse 'kind' for a call: (tool, specifier).

    Bash keys on the leading command word (`git status` -> ("Bash", "git")),
    so remembering one `git` approval covers later `git` commands. Other tools
    key on the tool name alone.
    """
    if tool_name == "Bash":
        command = str(tool_input.get("command", "")).strip()
        first = command.split(maxsplit=1)[0] if command else ""
        return ("Bash", first)
    return (tool_name, "")


def describe_key(key: tuple[str, str]) -> str:
    tool, spec = key
    if tool == "Bash" and spec:
        return f"all `{spec} …` commands"
    return f"all {tool} calls"


def _has_shell_operator(tool_input: dict) -> bool:
    command = str(tool_input.get("command", ""))
    return any(op in command for op in _SHELL_OPERATORS)


class PermissionPolicy:
    """Decides which tool calls skip the dialog (session-scoped)."""

    def __init__(self, auto_allow: frozenset[str] = AUTO_ALLOW_TOOLS) -> None:
        self._auto_allow = auto_allow
        self._remembered: set[tuple[str, str]] = set()

    def auto_allow(self, tool_name: str, tool_input: dict) -> bool:
        if tool_name in self._auto_allow:
            return True
        # Chained shell commands always re-prompt, even if the prefix is known.
        if tool_name == "Bash" and _has_shell_operator(tool_input):
            return False
        return similarity_key(tool_name, tool_input) in self._remembered

    def remember(self, tool_name: str, tool_input: dict) -> None:
        self._remembered.add(similarity_key(tool_name, tool_input))
