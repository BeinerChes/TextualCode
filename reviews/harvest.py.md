# Code Review — `textualcode/harvest.py`

**Reviewed:** 2026-06-03 (post-hardening state) · **Dimensions:** General Python · Claude SDK · Efficiency · Security
**Method:** 4 parallel specialist agents, each web-search-backed against authoritative sources.

## Overall assessment

The recent hardening landed well (sentinel fence, `tools=[]` + `disallowed_tools`, `setting_sources=[]`, `strict_mcp_config=True`, `max_turns`/`max_budget_usd`, safe `json.loads`). **But the security agent found a CRITICAL the hardening didn't cover, and the SDK agent found that our newly-added `is_error` is inert:**

1. 🔴 **CRITICAL — path traversal / arbitrary file write:** the model-controlled `slug` is used verbatim as a filename (sink in `lessons.py`); `_slugify` is applied *only* as a fallback for empty slugs. A prompt-injected transcript can write attacker-controlled markdown outside `.claude/lessons/`.
2. 🟠 **MAJOR — `is_error` not load-bearing:** we added `is_error` + caps, but no caller checks it, so hitting `max_turns`/`max_budget_usd` now returns "success" with empty output and `harvest_controller` still writes files + reports success.

| Severity | Count |
|----------|-------|
| Critical | 1 |
| Major    | 1 |
| Minor    | 3 |
| Nit      | 4 |

---

## 🔒 Security

> harvest.py is the trust boundary where an isolated model's JSON reply becomes structured data persisted to disk. Isolation/deserialization controls are good. The exploitable issue is using a model-controlled value as a filesystem path.

**Sources:** [CWE-22](https://cwe.mitre.org/data/definitions/22.html) · [OWASP LLM05 Improper Output Handling](https://genai.owasp.org/llmrisk/llm02-insecure-output-handling/) · [Snyk: insecure output handling](https://learn.snyk.io/lesson/insecure-output-handling/)

### 🔴 [CRITICAL] Path traversal via unsanitized model-controlled slug (`_parse` L140-149, esp. L145; sink: `lessons.py` `_write_lessons` L86)
`slug=str(item.get("slug") or "").strip() or _slugify(rule)` — `_slugify` (which restricts to `[a-z0-9-]`) runs **only when the model omits/empties slug**; a non-empty model-supplied slug bypasses all sanitization. `lessons.py` then builds `lessons_dir / f"{lesson.slug}.md"` and `write_text()`s **model-controlled content** to it. A reply with `slug="../../../../Users/x/.bashrc"` or an absolute path writes outside `.claude/lessons/`. The threat model explicitly treats transcript + model output as untrusted (per in-file comments / `EXTRACTION_PROMPT`), and a successful injection past the fence can steer the slug. This is an arbitrary-file-write primitive with attacker-influenced content. `test_isolated_clients.py:352` currently asserts the verbatim passthrough as *intended* — no traversal test exists.
- **Fix (sanitize at this boundary, always):** `cand = _slugify(str(item.get("slug") or "")); slug = cand if cand != "lesson" else _slugify(rule)` — `_slugify` already neutralizes `..`, `/`, `\`, drive letters, absolute paths, and caps length.
- **Defense-in-depth (`lessons.py`):** `resolve()` the final path and assert `is_relative_to(lessons_dir.resolve())` before writing.
- **Tests:** update `test_isolated_clients.py` to assert `"../../../foo"`, `"/etc/passwd"`, `"a/b"` are sanitized.

### [MINOR] Unconstrained model text fields → markdown/index injection (`_parse` L138-165; `category` L146-148, `rule` L142-143, `_as_list` fields)
`category`, `rule`, `goal`, etc. are stored with only `.strip()` — no length/newline/metachar limits. `lessons.py._render_index` emits `## {category}` and `- [..](..) — {rule}` into `INDEX.md`; a `category` with a newline or `## ` can forge index sections, and `rule`/`keyfiles` with `[`/`]`/backticks can corrupt markdown. Not code-exec, but a prompt-injected transcript could plant misleading guidance into `INDEX.md`/`state.md` that a future agent reads. (OWASP Improper Output Handling.)
- **Fix:** Collapse/strip newlines for single-line fields (`category`, `slug`, `satisfied`); cap lengths (`category`≤40, `rule`≈300); consider a `category` allowlist.

### [NIT] No size bound before `json.loads` (`_extract_json` L82-91)
`json.loads` (no eval/pickle) is the correct, safe choice. Only residual: no upper bound on parsed object size — largely mitigated by `max_turns=2` + budget cap.
- **Fix:** Optional — bound `len(text)` before `json.loads` as defense-in-depth. Keep `json.loads`.

---

## 🤖 Claude SDK

> Verified against installed 0.2.88. Usage correct; one major (inert `is_error`) and one nit.

**Sources:** [SDK CHANGELOG](https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md) · [types.py](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py) · [SDK Python docs](https://code.claude.com/docs/en/agent-sdk/python)

### 🟠 [MAJOR] `is_error` stored but never inspected (`run` L131, `HarvestResult.is_error` L71)
Error terminations (`error_max_budget_usd`, `error_max_turns`, `error_during_execution`) **don't raise** inside the `receive_response` loop — they set `is_error=True`. With `max_turns=2` and `max_budget_usd=0.10`, hitting either cap returns `is_error=True` with an empty `parts` buffer, **yet `harvest_controller` still writes files and reports success**. The SDK changelog fixed `is_error` for these subtypes precisely so pipelines stop treating a cap as success. *(This is the natural follow-on to adding `is_error` + caps in the last fix batch — we must now make it load-bearing.)*
- **Fix:** Check `result.is_error` in `Harvester.run` or `HarvestController.run` before `write_harvest` + the success message; optionally surface `ResultMessage.subtype` / `api_error_status` for a precise message.

### [NIT] Only `TextBlock` collected (`run` L124-127)
Correct for a JSON-only no-tools agent, but a non-text block leaves `parts` empty and `_extract_json` returns `None` — indistinguishable from malformed JSON.
- **Fix:** If `parts` is empty after the loop, report distinctly or route into the `is_error` error path.

---

## 🐍 General Python

> Small, clean, well-documented (`from __future__ import annotations`, PEP 585 generics, dataclasses w/ `default_factory`, narrow `except json.JSONDecodeError`, `async with`). Findings are typing-completeness only.

**Sources:** [PEP 484](https://peps.python.org/pep-0484/) · [mypy strict codes](https://mypy.readthedocs.io/en/stable/error_code_list2.html) · [typing docs](https://docs.python.org/3.11/library/typing.html)

### [MINOR] Bare `dict | None` for `usage` (`HarvestResult` L69, `run` L116, `_parse` L136)
SDK types `ResultMessage.usage` as `dict[str, Any] | None`; bare `dict` ≈ `dict[Any, Any]` (flagged by `--disallow-any-generics`).
- **Fix:** Annotate `dict[str, Any] | None` consistently.

### [MINOR] `_extract_json` bare return `dict | None` (L82)
- **Fix:** `-> dict[str, Any] | None` (import `Any`).

### [MINOR] Untyped `_as_list(value)` param (L74)
Partially-annotated (return typed, param not) → flagged by `--disallow-untyped-defs`.
- **Fix:** `def _as_list(value: object) -> list[str]:` (`object` suffices — body only does `isinstance`/`str()`).

### [NIT] Dead default `is_error: bool = False` in `_parse` (L136)
Private static method; sole caller always passes it explicitly.
- **Fix:** Drop the `= False` default for an honest signature.

---

## ⚡ Efficiency

> **Good shape.** Single awaited non-blocking SDK call; list-of-parts + `join` (no quadratic concat); `_extract_json` is find/rfind/slice on a small payload run once. No nested loops, no blocking calls. One trivial nit.

**Sources:** [re.compile](https://pynative.com/python-regex-compile/)

### [NIT] Inline regex in `_slugify` (L44-46)
Pattern passed to `re.sub` per call rather than module-level compiled. Python caches patterns internally, so the difference is ~zero.
- **Fix (optional):** Hoist to a module-level compiled constant (convention only).

---

## Suggested priority

1. 🔴 **Sanitize `slug` at the parse boundary** (critical) — always run it through `_slugify`; add `is_relative_to` confinement in `lessons.py`; add traversal tests. **Top priority — arbitrary file write.**
2. 🟠 **Make `is_error` load-bearing** (major) — block `write_harvest` + success message on `is_error`. *(Completes the hardening we started.)*
3. Constrain `category`/`rule`/text fields (markdown/index injection); empty-`parts` handling.
4. Typing precision (bare `dict`, untyped param, dead default); regex hoist.

> **Cross-file note:** the critical and the markdown-injection minor both have their **sink in `lessons.py`** (not yet reviewed), and the `is_error` major involves **`harvest_controller.py`**. A fix task should touch `harvest.py` (sanitize at source) + `lessons.py` (path confinement, index escaping) + `harvest_controller.py` (honor `is_error`) together.
