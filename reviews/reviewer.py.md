# Code Review — `textualcode/reviewer.py`

**Reviewed:** 2026-06-03 · **Dimensions:** General Python · Claude SDK · Efficiency · Security
**Method:** 4 parallel specialist agents, each web-search-backed against authoritative sources.

## Overall assessment

`reviewer.py` is a small, clean, well-documented isolated-SDK-client module (mirrors `committer.py` / `harvest.py`). Python/SDK/efficiency findings are idiomatic improvements, not bugs. **The headline is security:** this component ingests the *untrusted* working-tree diff (including raw untracked file contents) directly into the prompt, holds `WebFetch`/`WebSearch` + read tools, and runs under `permission_mode="bypassPermissions"` — a textbook indirect-prompt-injection → exfiltration surface.

| Severity | Count |
|----------|-------|
| Critical | 0 |
| Major    | 3 |
| Minor    | 5 |
| Nit      | 4 |

---

## 🔒 Security

> Isolated client ingests attacker-influenceable diff content into the prompt with no quarantine; has an outbound network channel (`WebFetch`) + full repo read access (secrets/.env/keys); runs autonomously with no user gate. The read-only restriction itself **is** correctly enforced (Python SDK 0.2.88 `tools=` sets the base built-in set — `Bash/Write/Edit` genuinely absent; the TS issue #115 does *not* apply here).

**Sources:** [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) · [Prompt-Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) · [AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) · [CWE-918 / agentic SSRF](https://blogs.jsmon.sh/prompt-injection-to-ssrf-exploiting-ai-agents-and-tool-calling/) · [OWASP LLM10 Unbounded Consumption](https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/)

### [MAJOR] Indirect prompt injection over untrusted diff (L71-74; `_REVIEW_TOOLS` L33; `permission_mode` L61; `prompts.py:REVIEW_PROMPT`)
The working-tree diff (raw untracked file contents + added lines — all attacker-influenceable via a malicious dependency/vendor file, a checked-out branch/PR, or an LLM artifact) is concatenated verbatim into the user message (`"Review the following uncommitted working-tree diff:\n\n{diff_text}"`) with **no delimiting, no quarantine, and no instruction to treat it strictly as data**. The reviewer holds `WebFetch`/`WebSearch` + read tools under `bypassPermissions`, so embedded instructions are followed autonomously. Canonical OWASP LLM01.
- **Fix:** Wrap the diff in a hard-to-spoof per-run sentinel fence and add a `REVIEW_PROMPT` line stating everything inside the fence is untrusted DATA to review, never instructions to execute. Mitigation only — pair with egress restriction below.

### [MAJOR] Exfiltration / SSRF channel under autonomous execution (L33 `WebFetch`+`Read/Grep/Glob`; `permission_mode` L61)
The reviewer can `Read/Grep/Glob` the entire project (incl. `.env`, keys, tokens — none excluded) **and** make arbitrary outbound requests via `WebFetch`, all under `bypassPermissions` (no approval). Combined with the injection vector, a crafted file can instruct the reviewer to read a secret and encode it into a `WebFetch` URL — silent exfiltration (CWE-918). The L61 comment ("autonomous; tools are read-only") understates this: read-only still reads secrets, and `WebFetch` is the egress.
- **Fix:** Remove `WebFetch` (prefer `WebSearch`, which has no model-controlled `fetch(url)` primitive) or constrain egress to a fixed doc-domain allowlist. Don't pair outbound network with full repo read under `bypassPermissions`.

### [MINOR] Unbounded consumption — no `max_turns` / `max_budget_usd` (L55-64; receive loop L75-83)
Neither cap is set; the receive loop only breaks on `ResultMessage`, so a tool-call loop (from a hard diff or injection deliberately steering into one) runs unbounded turns and uncapped cost on every Review press. Both fields exist in installed SDK (`types.py:1653` / `1659`). OWASP LLM10.
- **Fix:** Set conservative `max_turns` and a `max_budget_usd` ceiling so a runaway terminates deterministically.

### [NIT] No `disallowed_tools` backstop (L55-64)
Read-only relies solely on the `tools=` base allowlist (correct in 0.2.88). But under `bypassPermissions`, a future edit broadening `tools` to a preset or dropping the list would make `Bash/Write/Edit` available and auto-approved with no second barrier.
- **Fix:** Add `disallowed_tools=["Bash","Write","Edit","NotebookEdit"]` (SDK strips these even if otherwise allowed — `types.py:1666-1671`).

---

## 🐍 General Python

> Small, clean, well-documented; follows project conventions (`from __future__ import annotations`, `X | None`, dataclass result, narrow imports). Findings are quality/idiomatic.

**Sources:** [PEP 484](https://peps.python.org/pep-0484/) · [PEP 8](https://peps.python.org/pep-0008/) · [implicit-Optional deprecated](https://adamj.eu/tech/2022/10/18/python-type-hints-implicit-optional-types/) · [contextlib](https://docs.python.org/3/library/contextlib.html)

### [MAJOR] Untyped `cwd` parameter (`__init__` L48)
`cwd=None` is the only unannotated parameter in the module (inconsistent with the rest of the codebase) and is an implicit-Optional (PEP 484 deprecated). Passed straight to `ClaudeAgentOptions(cwd=...)`; callers pass a path-like.
- **Fix:** `cwd: str | Path | None = None` (`from pathlib import Path`), annotate `self._cwd` too. Verify the exact type `ClaudeAgentOptions.cwd` accepts.

### [MINOR] Manual `connect()`/`try-finally`/`disconnect()` instead of `async with` (run L65-86)
SDK documents `ClaudeSDKClient` as an async context manager — idiomatic and less error-prone than hand-rolled teardown. (Pattern is duplicated in `committer.py`/`harvest.py` — a project-wide consistency choice.)
- **Fix:** `async with ClaudeSDKClient(options=options) as client:` with the query/receive loop inside; apply consistently across the three isolated-client modules.

### [MINOR] `receive_messages()` + manual `break` instead of `receive_response()` (run L75-83)
*(Also raised by SDK and Efficiency agents.)* SDK provides `receive_response()` — the documented convenience iterator that yields up to and including `ResultMessage` then stops. `receive_messages()` is for manual/early-exit control (e.g. `interrupt()`), unused here.
- **Fix:** `async for message in client.receive_response():`, drop the `break`; capture usage/cost on `ResultMessage`.

### [NIT] Bare `dict` generics (L41,68,69,81 — `usage: dict | None`, `cost`)
PEP 484 prefers parameterized generics (`dict[str, Any]` or a TypedDict). Consistent with project convention (`accounting.py`, `harvest.py`, `stats.py`).
- **Fix:** Optionally tighten to `dict[str, Any]` / a usage TypedDict — project-wide if pursued.

### [NIT] Implicit string concatenation mixing literal + f-string (run L71-74)
Works, but slightly easy to misread (same shape in `committer.py:67-69`).
- **Fix:** Single f-string: `f"Review the following uncommitted working-tree diff:\n\n{diff_text}"`.

---

## 🤖 Claude SDK

> SDK 0.2.88 usage mostly correct for an isolated read-only review client.

**Sources:** [SDK Python docs](https://code.claude.com/docs/en/agent-sdk/python) · [permissions](https://code.claude.com/docs/en/agent-sdk/permissions) · [cost-tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking)

### [MINOR] Use `receive_response` instead of `receive_messages`+break (L75-83)
*(See Python/Efficiency.)*

### [MINOR] `allowed_tools` does not constrain `bypassPermissions` (L60-61)
Only `tools=` constrains the base built-in set; `allowed_tools` is ineffective under `bypassPermissions`.
- **Fix:** Drop `allowed_tools` (rely on `tools=`) or use a `dontAsk`-style mode.

### [NIT] `is_error` never checked (L80-83)
An errored review silently returns empty text.
- **Fix:** Surface `is_error` on `ReviewResult`.

---

## ⚡ Efficiency

> **Efficient.** Single network-bound async query; text accumulated in a list and `join`-ed once (no quadratic concat); no large loops, no redundant recomputation, no blocking I/O of its own (caller offloads the git diff via `asyncio.to_thread`). One minor idiom note.

**Sources:** [SDK Python ref](https://docs.claude.com/en/docs/agent-sdk/python) · [SDK repo](https://github.com/anthropics/claude-agent-sdk-python) · [PEP 525](https://peps.python.org/pep-0525/) · [async-generator cleanup](https://samgeo.codes/python-generator-cleanup/)

### [MINOR] Early `break` out of `receive_messages` relies on finalizer-driven `aclose` (run L75-83)
Breaking out of an async generator early doesn't synchronously close it; cleanup defers to GC-scheduled `aclose` via `GeneratorExit` (fragile per PEP 525). The trailing `finally: disconnect()` tears down the transport so it's not a real leak — but `receive_response` (installed source `client.py` ~L603-606) returns cleanly and is the recommended pattern.
- **Fix:** Iterate `receive_response` and drop the `break`.

---

## Suggested priority

1. **Quarantine the untrusted diff** in the prompt (security major) — sentinel fence + "data not instructions" directive.
2. **Close the exfiltration channel** (security major) — drop `WebFetch` or allowlist egress; don't combine network + secret-read under `bypassPermissions`.
3. **Cap turns/budget** (security minor) — `max_turns` + `max_budget_usd`.
4. **Switch to `receive_response`** (SDK/Python/Efficiency — three agents agree).
5. Add `disallowed_tools` backstop; type `cwd`; `async with`; check `is_error`; nits.
