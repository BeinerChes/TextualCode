# Code Review — `textualcode/dispatcher.py`

**Reviewed:** 2026-06-03 · **Dimensions:** General Python · Claude SDK · Efficiency · Security
**Method:** 4 parallel specialist agents, each web-search-backed against authoritative sources.

## Overall assessment

`dispatcher.py` is small, clean, and idiomatic (3.11+ idioms, keyword-only args, `TYPE_CHECKING`, context-managed file handle). **No correctness bugs, no SDK defects.** All findings cluster around two things: (1) **typing precision** at the public surface, and (2) the **debug-only `TaskDebugLog.record()`** path (efficiency + a log-injection hygiene issue). Everything in the debug logger is gated behind `TEXTUALCODE_DEBUG_TASKS`, so its issues only bite developers who enable it.

| Severity | Count |
|----------|-------|
| Critical | 0 |
| Major    | 0 |
| Minor    | 5 |
| Nit      | 5 |

---

## 🔒 Security

> Core dispatch is fine. The only findings are in the opt-in debug logger.

**Sources:** [CWE-117 Log Injection](https://cwe.mitre.org/data/definitions/117.html) · [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) · [CWE-532](https://cwe.mitre.org/data/definitions/532.html)

### [MINOR] Log injection — un-neutralized CRLF in `TaskDebugLog.record()` (L49-55)
Untrusted SDK fields (`task_id`, `tool_use_id`, `usage`) are interpolated raw (no `repr`), so embedded newlines can forge/split log lines (CWE-117). `description`/`summary` are incidentally safe because they go through `repr`.
- **Fix:** Neutralize CR/LF on every interpolated untrusted field, or apply `repr` uniformly to `task_id`/`tool_use_id`/`usage` (as already done for `description`).

### [NIT] Unbounded append-only debug log (L54-57)
Persists raw usage/metadata to an unprotected file with no rotation/size cap (CWE-532 hygiene).
- **Fix:** Ensure `task-debug.log` is gitignored and documented as developer-only; review before adding any free-text/sensitive fields.

---

## ⚡ Efficiency

> Clean overall; both findings are in the debug-only logger.

**Sources:** [open/append](https://coderivers.org/blog/python-open-file-append/) · [asyncio-dev](https://docs.python.org/3/library/asyncio-dev.html)

### [MINOR] Per-message open/write/close + Path rebuild (`record` L48-57)
Under `TEXTUALCODE_DEBUG_TASKS`, the log is opened/written/closed once per Task message, rebuilding the `Path` each call. Each open is a syscall; `TaskProgress` arrives frequently.
- **Fix:** Reuse one open handle (lazy/in `__init__`) or a `logging.FileHandler` with buffering; cache the `Path`.

### [MINOR] Blocking file I/O on the event-loop thread (`handle`→`record`, L88, L56-57)
`record` does synchronous `open/write/close` called from async `handle` awaited on the event-loop pump thread (`app.py:373`), stalling the loop per message when enabled.
- **Fix:** Offload (`asyncio.to_thread` / `logging.QueueHandler`) or keep a buffered open handle.

---

## 🐍 General Python

> Structure is sound (`from __future__ import annotations`, keyword-only ctor args, `TYPE_CHECKING`, context-managed handle, justified logging guard). Actionable items are typing precision.

**Sources:** [PEP 484](https://peps.python.org/pep-0484/) · [typing docs](https://docs.python.org/3/library/typing.html) · [PEP 563](https://peps.python.org/pep-0563/) · [PEP 8](https://peps.python.org/pep-0008/) · [PEP 257](https://peps.python.org/pep-0257/)

### [MINOR] Bare `Callable` collaborators (ctor L72-74)
`accrue_subagent_tokens` / `on_turn_complete` / `on_stream_progress` are typed as bare `Callable` (≈ `Callable[..., Any]`), giving checkers no signature info. Call sites are concrete and knowable.
- **Fix:** Subscript: `accrue_subagent_tokens: Callable[[<UsageType>], None]`, `on_turn_complete: Callable[[], None]`, `on_stream_progress: Callable[[AssistantMessage], None] | None = None` (at minimum `Callable[..., None]`).

### [MINOR] Untyped `message` parameter (`_task_key` L28, `record` L44, `handle` L84)
`message` is implicitly `Any` in three functions, disabling type checking in the most logic-dense part (the dispatch body), while the rest of the module is carefully typed.
- **Fix:** Add a module union alias, e.g. `SDKMessage = AssistantMessage | ResultMessage | TaskNotificationMessage | TaskProgressMessage | TaskStartedMessage` (or the SDK's existing base/union if one exists — verify against `claude_agent_sdk` source), annotate `message: SDKMessage`. For the duck-typed `getattr` paths, even `object` beats implicit `Any`.

### [NIT] Redundant quoted forward refs (ctor L68-70)
`"MessageRenderer"`, `"Transcript"`, `"TaskPanel"` are string-quoted despite `from __future__ import annotations` (PEP 563 already stringifies all annotations), and inconsistent with unquoted forms elsewhere (`debug_log: TaskDebugLog`).
- **Fix:** Drop the quotes.

### [NIT] Double `isinstance(message, AssistantMessage)` in `handle()` (L84-111)
Correct but mixes early-return and fall-through styles; re-runs the same `isinstance` twice in the hot path.
- **Fix (optional):** Compute `is_assistant = isinstance(message, AssistantMessage)` once and reuse.

---

## 🤖 Claude SDK

> SDK usage correct and idiomatic for 0.2.88; all message types and field accesses verified against installed source + docs. No defects; two optional nits.

**Sources:** [SDK Python docs](https://code.claude.com/docs/en/agent-sdk/python)

### [NIT] Task cards keyed by `task_id`+description, not `tool_use_id` (L90-94)
Every Task message carries the SDK `tool_use_id`; keying on it is more robust.
- **Fix:** Key by `tool_use_id` with fallback to `task_id`+description.

### [NIT] Subagent tokens only from `TaskNotificationMessage.usage` (L96-101)
Tokens are lost on failed/stopped tasks; `TaskProgressMessage.usage` is used only for display.
- **Fix:** Fall back to the last `TaskProgressMessage.usage` per `task_id`.

---

## Suggested priority

1. **Log-injection neutralization** in `record()` (security minor) — `repr`/CRLF-strip untrusted fields.
2. **Type the dispatch surface** (python minor) — `SDKMessage` union + `Callable[...]` signatures; enables static checking of the core logic.
3. Debug-logger efficiency (buffered handle / offload) — only matters when `TEXTUALCODE_DEBUG_TASKS` is on.
4. Gitignore/document `task-debug.log`; drop redundant quotes; SDK keying nits.

> Note: all debug-logger findings share one root cause — `TaskDebugLog` reopening the file per message and interpolating raw fields. A single refactor (buffered `logging.FileHandler` + `repr` on all fields) resolves the security, both efficiency, and the hygiene findings at once.
