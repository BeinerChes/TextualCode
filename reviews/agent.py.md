# Code Review — `textualcode/agent.py`

**Reviewed:** 2026-06-03 · **Dimensions:** General Python · Claude SDK · Efficiency · Security
**Method:** 4 parallel specialist agents, each web-search-backed against authoritative sources.

## Overall assessment

`agent.py` is a clean, well-organized thin async wrapper around `ClaudeSDKClient`. **No correctness bugs and no efficiency problems.** The substantive issues are:
1. **Security (major):** fail-open permission defaults — `_approve_tool` / `_answer_question` return *Allow* when no handler is configured.
2. **Python typing (major):** the SDK permission callback `_approve_tool` is fully untyped at the one public-protocol seam.
3. Several minor typing/SDK/security hardening items.

| Severity | Count |
|----------|-------|
| Critical | 0 |
| Major    | 2 |
| Minor    | 8 |
| Nit      | 3 |

---

## 🔒 Security

> The `_approve_tool` callback is the runtime gate deciding which tool calls (Bash, Write, Edit, MCP) execute. Dominant risk is fail-open defaults. MCP trust-gate (`strict_mcp_config`) and session-only permission memory are sound. No injection / path traversal / unsafe deserialization in this file.

**Sources:** [SDK permissions docs](https://code.claude.com/docs/en/agent-sdk/permissions) · [secure-deployment](https://platform.claude.com/docs/en/agent-sdk/secure-deployment) · [CWE-636](https://cwe.mitre.org/data/definitions/636.html) · [CWE-78](https://cwe.mitre.org/data/definitions/78.html)

### [MAJOR] Fail-open default in `_approve_tool` (L221-222)
When `self._permission_handler is None`, the callback returns `PermissionResultAllow()`, auto-approving **any** tool call (Bash/Write/Edit/MCP) with no prompt. A construction path or future refactor that drops the handler silently grants unrestricted, unattended execution (CWE-636 Insecure Defaults / CWE-665 Improper Initialization).
- **Fix:** Fail closed — return `PermissionResultDeny(message="No permission handler configured.")`. If a no-prompt mode is intended, make it an explicit named opt-in (`auto_approve: bool`) and document it. At minimum assert/log when the handler is None so the open state is never silent.

### [MINOR] Fail-open default in `_answer_question` (L237-238)
When `self._question_handler is None`, proceeds via `PermissionResultAllow()` ("proceed unanswered"). Repeats the fail-open pattern; lets the model continue without requested user input.
- **Fix:** Prefer `PermissionResultDeny(message="No question handler configured.")`, or gate "proceed unanswered" behind the same explicit opt-in flag.

### [MINOR] Authority dilution from `setting_sources=["user","project"]` (L82-91)
Per SDK evaluation order (Hooks → Deny → Permission mode → Allow rules → canUseTool), `permissions.allow` rules in user/project `.claude/settings.json` are evaluated and can auto-approve tools **before** `_approve_tool` runs. A broad allow-rule (e.g. `Bash(*)`) in an untrusted repo's checked-in settings can green-light dangerous tools without ever reaching this app's dialog. Already acknowledged in a code comment, but deserves an explicit decision.
- **Fix:** Treat checked-in project settings as untrusted — consider `setting_sources=["user"]` and inject project `CLAUDE.md` separately, OR keep `"project"` but add a `disallowed_tools` deny-list / PreToolUse hook for high-risk patterns that project allow-rules can't override.

### [MINOR] Coarse first-word Bash auto-allow (L219; policy in `permissions.py`)
Session-memory keys remembered Bash approvals on the **first word only**, so one `git` approval green-lights every later `git …`. The `_SHELL_OPERATORS` denylist blocks chaining/substitution/redirection (good) but not argument-injection within an allowed word (`git -c …`, `git ... --exec`, `find . -exec`, `npm run <script>`), single `&` backgrounding, or brace expansion. Blast radius limited (first call still prompts; memory session-scoped). CWE-78 class.
- **Fix:** Document the coarse-by-design choice; if tightening, add `&`, `{`, `}` to `_SHELL_OPERATORS` and key on a longer normalized prefix (subcommand) for high-variance tools (e.g. `git status` vs `git push`).

### [NIT] Unvalidated answer pass-through in `_answer_question` (L242-244)
`updated_input` is built from model-supplied `questions` + user-supplied `answers` and returned verbatim with no check that answers match offered labels. Not a vuln today (answers come from the local user), but worth a guard before any free-text answer path is added.
- **Fix:** When free-text answers arrive, validate each answer against the question's offered options before constructing `updated_input`.

---

## 🐍 General Python

> Clean and well-organized. Typing and error-handling improvements only; not correctness bugs.

**Sources:** [PEP 484](https://peps.python.org/pep-0484/) · [PEP 585](https://peps.python.org/pep-0585/) · [exception-handling best practices](https://www.qodo.ai/blog/6-best-practices-for-python-exception-handling/)

### [MAJOR] Untyped SDK callback `_approve_tool` (L215-228)
Fully untyped params and return on the SDK callback. SDK 0.2.88 `types.py` exports the exact `CanUseTool` signature: `Callable[[str, dict[str, Any], ToolPermissionContext], Awaitable[PermissionResult]]`. Implicit `Any` defeats type-checking at the one public-protocol seam; `context` is also unused.
- **Fix:** Annotate `tool_name: str`, `tool_input: dict[str, Any]`, `context: ToolPermissionContext`, return `PermissionResult`; rename unused `context` → `_context`.

### [MINOR] Missing return annotations (`_answer_question` L230-244, `_approve_tool`)
Both return the SDK `PermissionResult` union but have no return annotation; inferred type is `Any`.
- **Fix:** Add `-> PermissionResult` to both.

### [MINOR] Bare `dict` / `list[dict]` (L24,26,39,49,110,148,157,230)
Bare collection types convey no key/value typing; PEP 585 prefers `dict[str, Any]` (as the SDK uses for these shapes).
- **Fix:** Use `dict[str, Any]` / `list[dict[str, Any]]` on handlers, `available_models`, `context_usage`, `mcp_status`.

### [MINOR] Silent broad `except` (L154,169,202)
Broad `except` returns a default with no logging; a real SDK regression would silently look "feature-unsupported". `# noqa: BLE001` documents intent but hides runtime failures.
- **Fix:** Log via a module logger with `exc_info` before returning the fallback.

### [NIT] `tools` tri-state only documented in comments (param L39, attr L51)
Tri-state semantics (`None`=all, `[]`=none, subset=those) live only in comments; passing empty default silently disables all tools.
- **Fix:** Add a named sentinel or docstring note on `__init__`.

---

## 🤖 Claude SDK

**Sources:** [user-input docs](https://code.claude.com/docs/en/agent-sdk/user-input) · [claude-code#18735](https://github.com/anthropics/claude-code/issues/18735)

### [MINOR] `tools` subset must include `AskUserQuestion` (connect, L73)
If a `question_handler` is set but the `tools` subset omits `AskUserQuestion`, the handler is dead code.
- **Fix:** Append `AskUserQuestion` to the tools list when `question_handler` is set.

### [MINOR] No PreToolUse keep-alive hook (connect, L64-95)
The `can_use_tool` callback only stays alive via the persistent empty stream; there's no PreToolUse keep-alive hook.
- **Fix:** Add a comment documenting that the empty stream keeps `can_use_tool` alive (or add an explicit keep-alive).

---

## ⚡ Efficiency

> **No findings.** Thin async wrapper around `ClaudeSDKClient`; all methods are awaited network/IPC I/O with no CPU-bound work, no blocking sync calls, no subprocess use, no large data structures. Loops are over tiny config sets only. Permission checks use `frozenset`/`set` O(1) membership. The only micro-cost is the pass-through async generator in `messages()` (one extra frame per network-paced message — immaterial).

**Sources:** [asyncio-dev](https://docs.python.org/3/library/asyncio-dev.html) · [Real Python async-io](https://realpython.com/async-io-python/) · [SDK Python ref](https://docs.claude.com/en/api/agent-sdk/python) · [pylint#4776](https://github.com/PyCQA/pylint/issues/4776)

---

## Suggested priority

1. **Fix fail-open permission defaults** (security major) — fail closed in `_approve_tool` / `_answer_question`.
2. **Type the `_approve_tool` callback** (python major) using the SDK's `CanUseTool` signature.
3. Add `AskUserQuestion` to tools when a question handler is set (SDK).
4. Decide & document the `setting_sources` trust posture (security minor).
5. Logging in broad excepts; typing of bare dicts; remaining nits.
