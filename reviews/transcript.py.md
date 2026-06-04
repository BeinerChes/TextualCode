# Code Review — `textualcode/transcript.py`

**Reviewed:** 2026-06-03 · **Dimensions:** General Python · Claude SDK · Efficiency · Security
**Method:** 4 parallel specialist agents, each web-search-backed against authoritative sources.

## Overall assessment

**Essentially clean.** A small, well-written string-accumulator dataclass: modern idioms (`from __future__ import annotations`, PEP 585 generics, `field(default_factory=list)`, full return annotations), correct O(n) list-append + single `join`, sound encapsulation. **No correctness, typing, efficiency, or exploitable security issues.** All findings are nit-level (one minor SDK completeness item). Notably, the SDK and Security agents both call out that this file's *omissions* (dropping tool I/O, only recording tool name) are **deliberate positives** for cost and injection/secret minimization.

| Severity | Count |
|----------|-------|
| Critical | 0 |
| Major    | 0 |
| Minor    | 1 |
| Nit      | 6 |

---

## 🤖 Claude SDK

> Correct/idiomatic for 0.2.88; imports are valid public exports; field accesses match installed dataclasses; the isinstance-over-`content` loop is the documented pattern. Observations concern intentionally-dropped block types.

**Sources:** [types.py](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py) · [SDK Python docs](https://docs.claude.com/en/docs/agent-sdk/python)

### [MINOR] `ServerToolUseBlock` dropped from transcript (`add_assistant` L27-35)
The loop records only `TextBlock` and `ToolUseBlock`. A `ServerToolUseBlock` (server-side web_search/web_fetch/code_execution) is silently dropped, so a server-side action records nothing — yet it's the same "action taken" signal `TOOL_CALL` captures for client-side tools. For a transcript handed to the harvester, this loses meaningful context. *(Same root as the `renderer.py` server-tool-block gap.)*
- **Fix:** `elif isinstance(block, ServerToolUseBlock): self._turns.append(f"TOOL_CALL: {block.name}")`. If intentionally excluded, add a comment.

### [NIT] Non-exhaustive `ContentBlock` handling undocumented (`add_assistant` L28-35)
6-member union handled non-exhaustively with no comment.
- **Fix:** One-line comment noting only `TextBlock`/`ToolUseBlock` are recorded by design.

---

## 🔒 Security

> Pure data-collection layer — no subprocess/path/deserialization/markup/secret handling of its own. Its `render()` output feeds the harvester and is persisted to `state.md`, but **both downstream risks are correctly mitigated in the consumer** (`harvest.py` sentinel fence + `tools=[]` + EXTRACTION_PROMPT). Findings are defense-in-depth notes, not flaws.

**Sources:** [CWE-532](https://cwe.mitre.org/data/definitions/532.html) · [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) · [Prompt-Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)

### [NIT] Verbatim capture — secrets persisted in cleartext (`add_user` L22-25, `add_assistant` L27-35)
Any secret in the conversation (pasted API key, echoed token) is captured and later persisted to `.claude/state.md` (often git-tracked) in cleartext (CWE-532). This is the single chokepoint where one redaction pass would protect all consumers. Not exploitable here — data only leaves via the explicit harvest action.
- **Fix (optional):** Mask obvious secret patterns (`sk-`, `ghp_`, `AKIA`, high-entropy tokens) in `add_user`/`add_assistant`/`render`, or at minimum document that captured turns may contain secrets persisted in cleartext.

### [NIT] Tool name only — deliberate positive (`add_assistant` L35)
Recording only `block.name` (dropping tool inputs/results) minimizes both secret exposure and the injection payload fed to the harvester. Flagged so a future change to capture full tool I/O is recognized as a potential regression.
- **Fix:** Keep name-only. If richer context is added, route through the harvest sentinel fence + a redaction pass and re-review.

### [NIT] `render()` returns untrusted text without a contract signal (L44-45)
The injection boundary is correctly applied at the consumer (`harvest.py`), but the producer gives no signal its output is untrusted — a future caller could feed `render()` to a model without a fence.
- **Fix:** Add a `render()` docstring note that the returned text is untrusted conversation data that must be wrapped in the per-run sentinel fence before any model sees it.

---

## 🐍 General Python

> Conforms to current guidance; only nit-level polish.

**Sources:** [PEP 257](https://peps.python.org/pep-0257/) · [PEP 8](https://peps.python.org/pep-0008/) · verified `_turns` is safe vs dataclass internals ([cpython#98886](https://github.com/python/cpython/issues/98886))

### [NIT] Missing one-line docstrings (`add_user` L22, `clear` L37, `empty` L41, `render` L44)
Public members inconsistently documented (class + `add_assistant` have docstrings).
- **Fix:** Add brief one-liners (PEP 257 permits omitting for truly obvious cases).

### [NIT] Parameter rebinding in `add_user` (L23-25)
`text = text.strip()` reassigns the parameter; `add_assistant` already uses a fresh local.
- **Fix:** Use a distinct local (`stripped = text.strip()`).

---

## ⚡ Efficiency

> **No findings.** `list[str]` append + single `"\n\n".join()` is the recommended O(n) pattern; per-call work is just `strip()` + `append` + isinstance dispatch. `render()` re-joins on each call but is invoked rarely (harvest only) — caching would be premature.

**Sources:** [string concat performance](https://realpython.com/python-string-concatenation/) · [ConcatenationTestCode](https://wiki.python.org/moin/ConcatenationTestCode)

---

## Suggested priority

This file needs **no action**. If touched opportunistically:
1. Record `ServerToolUseBlock` name (SDK minor) — batch with the same fix in `renderer.py`.
2. Document the `render()` untrusted-output contract + the intentional `ContentBlock` exclusions.
3. Optional secret redaction at this chokepoint (defense-in-depth for `state.md`).
4. Docstrings + parameter-rebind polish.

> **Cross-file note:** the `ServerToolUseBlock` gap recurs in `renderer.py` and here — a small shared decision (render/record server-tool activity) would close both.
