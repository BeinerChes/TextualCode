# Code Review — `textualcode/renderer.py`

**Reviewed:** 2026-06-03 · **Dimensions:** General Python · Claude SDK · Efficiency · Security
**Method:** 4 parallel specialist agents, each web-search-backed against authoritative sources.

## Overall assessment

`renderer.py` is a small, clean async dispatch/delegation layer. SDK field accesses are all verified-correct against installed 0.2.88, and the main-vs-subagent attribution via `parent_tool_use_id is None` is correct per Anthropic docs. **Two majors, both about what the renderer forwards rather than how it's written:**
1. **SDK:** it silently drops `ServerToolUseBlock`/`ServerToolResultBlock` — so **WebSearch/WebFetch activity is invisible** in the UI.
2. **Security:** it forwards raw, unescaped tool input into markup-interpreted Collapsible titles (sink in `tool_cards.py`) — a tool arg containing `[` breaks the card (the exact `escape-untrusted-cli-output-before-markup` lesson, unaddressed on this path).

| Severity | Count |
|----------|-------|
| Critical | 0 |
| Major    | 2 |
| Minor    | 1 |
| Nit      | 4 |

---

## 🔒 Security

> Thin presentation layer — no subprocess/deserialization/path handling. The one real issue is markup injection at the boundary the renderer creates: raw `ToolUseBlock` forwarded into markup-parsed Collapsible titles. Agent text is safe because it goes through the Markdown widget (markup not interpreted, ANSI stripped).

**Sources:** [Rich markup escaping](https://rich.readthedocs.io/en/latest/markup.html) · [CWE-150](https://cwe.mitre.org/data/definitions/150.html) — verified against installed Textual 8.2.7 source (`_collapsible.py`, `content.py`, `markup.py`)

### [MAJOR] Unescaped tool data → markup injection / denial-of-rendering (`_render_assistant` L57-67; sink: `tool_cards.py` `ToolCard.__init__` L43, `tool_preview` L11-19, `ToolGroupCard._summary` L92-98)
`render()`/`_render_assistant()` forward the raw `ToolUseBlock` to `ToolGroupCard.add_tool()`, which builds `ToolCard` titles from `block.name` and `tool_preview(block, ...)` (arbitrary `block.input` values: file paths, Grep/regex patterns, Bash commands, globs). In Textual 8.2.7, Collapsible titles are markup-parsed (`CollapsibleTitle.label = Content.from_text(label)` → `markup=True` → `to_content`, which **raises `MarkupError`** on malformed markup). A tool arg containing `[` (glob `[abc]*`, regex `interface\[\]`, bracketed path) is either reinterpreted as styling or raises `MarkupError`, breaking the conversation card. Same hazard as project lesson `escape-untrusted-cli-output-before-markup`, unaddressed here.
- **Fix (prefer at the sink in `tool_cards.py`):** wrap title components with `textual.markup.escape()` (`escape(block.name)`, `escape(tool_preview(...))`, escape each name in `_summary`), or build the title as non-markup `Content.from_text(title, markup=False)` / plain `Text`. Add a test feeding a tool name/preview with `[`/`]` to confirm literal rendering, no `MarkupError`.

### [NIT] Agent text safe-by-Markdown (defensive note) (`_render_assistant` L54-56 → `conversation.py:23` `Markdown`)
Model text renders through the Markdown widget, which neither interprets Rich/Textual markup nor raw ANSI (CWE-150 / cf. CVE-2025-55754 not reachable here). No change needed — flagged only to preserve the assumption.
- **Fix:** Keep agent text on `Markdown`. If ever switched to `from_markup`/`Static`/raw bytes, escape + strip control chars first. Optional regression test that `[red]x[/red]` renders literally.

---

## 🤖 Claude SDK

> Correct/idiomatic for 0.2.88; all imported names and field accesses match the installed dataclasses; isinstance dispatch is the documented pattern; subagent attribution validated against docs. One real gap: dropped content-block types.

**Sources:** [SDK Python docs](https://platform.claude.com/docs/en/agent-sdk/python) · [types.py](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py) · [agent-loop](https://platform.claude.com/docs/en/agent-sdk/agent-loop)

### [MAJOR] Dropped `ContentBlock` union members — WebSearch/WebFetch invisible (`_render_assistant` L53-67)
The per-block loop handles only `TextBlock` and `ToolUseBlock`, silently dropping `ServerToolUseBlock`, `ServerToolResultBlock`, `ThinkingBlock`, `ToolResultBlock` (`types.py:993-1000`). Since WebSearch/WebFetch are in the main agent's default toolset (`config.py:84-85`, `agent.py:81`), the API surfaces those as `ServerToolUseBlock`/`ServerToolResultBlock` (executed server-side) — so a user who grants WebSearch sees the agent visibly do web research but **the UI renders nothing**, appearing to stall/skip work. `ThinkingBlock` also dropped (lower impact — display defaults to 'omitted' on Opus 4.7+).
- **Fix:** Add an `elif isinstance(block, ServerToolUseBlock)` branch surfacing web_search/web_fetch in the tool group card (or a badge); import `ServerToolUseBlock`. At minimum handle each block type explicitly rather than silently falling through. Optionally add a `ThinkingBlock` branch for when thinking display is enabled.

### [NIT] Dead-ish `message.model and` guard (`_render_assistant` L51)
`AssistantMessage.model` is a required non-optional `str` (`types.py:1029`), so the truthiness guard defends a state the SDK doesn't promise.
- **Fix (optional):** Drop `message.model and` (just `if message.parent_tool_use_id is None:`), or keep it noting it guards an empty-string edge.

---

## 🐍 General Python

> Small, clean async dispatcher; modern idioms used well; no exception/resource handling needed; no correctness issues.

**Sources:** [PEP 585](https://peps.python.org/pep-0585/) · [PEP 257](https://peps.python.org/pep-0257/)

### [MINOR] Bare `dict` for `last_usage` / `last_model_usage` (L25, L28)
SDK types these as `dict[str, Any] | None`; rest of the file uses parameterized generics.
- **Fix:** Annotate `dict[str, Any] | None` (import `Any`); a TypedDict if the shape is stable.

### [NIT] Missing docstrings (class L20, `render` L40)
Public `MessageRenderer` and `render` lack docstrings (PEP 257/8).
- **Fix:** Add class + `render` docstrings; note the `last_cost`/`last_usage`/`last_model_usage` side effects.

---

## ⚡ Efficiency

> Almost pure delegation — no I/O, no subprocess, no nested loops, appropriate data structures (`set` for `main_models` O(1), scalar fields, isinstance dispatch O(1)). One minor batching note.

**Sources:** [Textual widget API](https://textual.textualize.io/api/widget/) · [Textual widgets guide](https://textual.textualize.io/guide/widgets/)

### [NIT] Per-block mount instead of batched render cycle (`_render_assistant` L53-67)
Each block awaits a separate mount+render (`add_message` mounts a row/gutter/Markdown + `scroll_end`; `add_tool` mounts separately). A multi-block `AssistantMessage` does N render cycles instead of one. Impact small — SDK normally streams one block per message.
- **Fix (defer):** If render churn appears, group same-type blocks and `mount_all`, and/or wrap per-message mounts in `async with self._view.batch():`.

---

## Suggested priority

1. **Escape tool data before markup** (security major) — fix at the `tool_cards.py` sink with `textual.markup.escape()` / `markup=False`; closes a known-lesson gap on this path. *(This finding implicates `tool_cards.py` — flag for its own review at `[8/40]`.)*
2. **Render server-tool blocks** (SDK major) — make WebSearch/WebFetch activity visible; handle all `ContentBlock` types explicitly.
3. Bare-`dict` typing; docstrings; drop dead `model` guard; defer batching.

> **Cross-file note:** both majors point at `tool_cards.py` (the title sink and the block-rendering target). Recommend reviewing/fixing `tool_cards.py` (already on the list as a SDK+Textual file) together with the renderer fixes.
