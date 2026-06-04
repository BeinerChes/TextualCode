# Code Review — `textualcode/tool_cards.py`

File [8/40]. Multi-agent review (Python, Claude SDK, Textual, Efficiency, Security), each web-search-backed against the installed versions (claude-agent-sdk 0.2.88, Textual 8.2.7).

## Overview

`tool_cards.py` is a small, clean UI module rendering streamed tool calls as
collapsible cards (`ToolCard`) and a compact group (`ToolGroupCard`). It is
idiomatic modern Python. The material issues are **two security majors**
(model-controlled markup injection / `MarkupError` DoS into `Collapsible`
titles — CWE-150), **one SDK major** (`ServerToolUseBlock` not handled, so
server tool calls are silently dropped upstream), and **one efficiency major**
(heavy `Markdown` widget used to render static JSON). Both the security and SDK
majors are the deferred `renderer.py` concerns recorded in `state.md`.

---

## Findings

### 🔒 Security — MAJOR: markup injection / `MarkupError` DoS via `ToolCard` title
- **Location:** `ToolCard.__init__` line 43 (`title` f-string) + `tool_preview` lines 11–19
- **Issue:** The title `f"🔧 {block.name}  {tool_preview(...)}"` is a raw `str`
  passed to `Collapsible`. In Textual 8.2.7, `Collapsible → CollapsibleTitle`
  calls `Content.from_text(label)` with `markup=True`, so any `[` in the title
  is parsed as Textual content markup. `block.name` and the preview echo
  model/MCP-controlled data — a tool named `evil[red]` injects styles/links, and
  an unmatched bracket raises `MarkupError` from `to_content`, crashing the card
  render (DoS). CWE-150.
- **Recommendation:** Build the title with `Content.from_markup` using
  `$`-substitution variables (brackets in substituted vars are preserved, not
  interpreted), or `rich.markup.escape()` the dynamic segments — matching how
  `screens.py` / `stats_panel.py` / `workspace_panel.py` already escape untrusted
  text in this repo.
- **Sources:** https://cwe.mitre.org/data/definitions/150.html ,
  https://textual.textualize.io/guide/content/ ,
  https://textual.textualize.io/api/markup/

### 🔒 Security — MAJOR: same markup sink in `ToolGroupCard` summary title
- **Location:** `_summary` lines 92–98, assigned at line 90 (`self.title = self._summary()`)
- **Issue:** `_summary()` joins `self._names` (each `block.name`, MCP-controlled)
  into a raw `str` assigned to `self.title`. `Collapsible._watch_title →
  CollapsibleTitle.label → Content.from_text(markup=True)` parses it as markup.
  Same CWE-150 injection / `MarkupError` crash, on the aggregated path
  (`add_tool` is awaited during streaming).
- **Recommendation:** Escape each name before joining, or assemble the summary as
  a `Content` via `Content.from_markup` with `$`-substitution. Use the same
  helper as the per-card title so both paths are covered.
- **Sources:** https://cwe.mitre.org/data/definitions/150.html ,
  https://textual.textualize.io/api/markup/

### 🤖 SDK — MAJOR: `ServerToolUseBlock` silently dropped (deferred renderer.py concern)
- **Location:** `tool_cards.py:7,11,37,81` (`ToolUseBlock`-only); upstream dispatch `renderer.py:13,57`
- **Issue:** The SDK `ContentBlock` union includes `ServerToolUseBlock`
  (web_search/web_fetch/code_execution/etc.). In claude-agent-sdk 0.2.88 it is a
  **separate dataclass**, not a subclass of `ToolUseBlock` (MRO is
  `(ServerToolUseBlock, object)`). So the upstream `isinstance(block,
  ToolUseBlock)` check in `renderer.py` (`_render_assistant`, ~line 57) is
  `False` for server-tool blocks → they never reach `ToolGroupCard`/`ToolCard`
  and vanish from the UI. The fields are identical (`id`/`name`/`input`), so the
  cards would render them fine via duck typing; only the dispatch and annotations
  exclude them.
- **Recommendation:** If server tools should show (recommended — they are real,
  billable actions): import `ServerToolUseBlock`, widen annotations to
  `ToolUseBlock | ServerToolUseBlock` in `tool_preview`, `ToolCard.__init__`,
  `ToolGroupCard.add_tool` (bodies unchanged), and fix the `renderer.py` dispatch
  to `isinstance(block, (ToolUseBlock, ServerToolUseBlock))`. If intentionally
  excluded, add a documenting comment in `renderer.py`.
- **Sources:** https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py ,
  https://docs.claude.com/en/docs/agent-sdk/python

### ⚡ Efficiency — MAJOR: heavy `Markdown` widget for static JSON
- **Location:** `ToolCard.__init__` lines 42–49, import line 8
- **Issue:** Each tool call wraps a static JSON dump in a Textual `Markdown`
  widget (`Markdown(f"```json\n{body}\n```")`). `Markdown` is the heaviest text
  widget: every block becomes its own child widget with its own event loop, and
  `Markdown.update()` instantiates a fresh `MarkdownIt("gfm-like")` parser and
  parses the whole string on each mount (verified in installed textual 8.2.7).
  The content is pre-formatted, non-streaming JSON needing only highlighted
  display — paying the full parse + per-block widget explosion per card compounds
  across a session.
- **Recommendation:** Render with a single `Static` containing a Rich `Syntax`:
  `Static(Syntax(body, "json", word_wrap=True))` (`from rich.syntax import
  Syntax`). One widget, no markdown-it parse. If highlighting is unneeded,
  `Static(body)` is cheapest.
- **Sources:** https://willmcgugan.github.io/streaming-markdown/ ,
  https://github.com/Textualize/textual/discussions/6414 ,
  https://github.com/Textualize/textual/issues/4586 ,
  https://textual.textualize.io/guide/content/

### 🔒 Security — MINOR: Markdown code-fence breakout in `_format_input` fallback
- **Location:** `_format_input` lines 22–29 (`text = str(data)` fallback), consumed at line 45
- **Issue:** Input is wrapped in a ` ```json ` fence. On the normal path
  `json.dumps` escapes newlines so embedded backticks stay inside; but the
  `except` fallback uses raw `str(data)`, which can contain real newlines + ```` ``` ````
  at column 0, terminating the fence early (breakout) and rendering
  model-controlled content as live Markdown. Lower severity (requires the
  `json.dumps` fallback; Markdown is a constrained sink). CWE-150 family.
- **Recommendation:** Neutralize backtick runs before embedding (e.g.
  `text.replace("```", "` ` `")`), use a longer fence, or fall back to `~~~`.
  Sanitize both the `json.dumps` and `str(data)` paths. (Moot if the efficiency
  fix replaces `Markdown` with `Static`+`Syntax`, which removes the fence sink
  entirely.)
- **Sources:** https://susam.net/nested-code-fences.html ,
  https://cwe.mitre.org/data/definitions/150.html

### 🐍 Python — MINOR: `compose` override missing `-> ComposeResult` annotation
- **Location:** `ToolGroupCard.compose`, line 71
- **Issue:** The override drops the `-> ComposeResult` return annotation the base
  `Collapsible.compose` declares; inconsistent with every other annotated
  function in the file and untyped under mypy --strict.
- **Recommendation:** `def compose(self) -> ComposeResult:` + `from textual.app
  import ComposeResult`.
- **Sources:** https://peps.python.org/pep-0484/

### 🐍 Python — MINOR: `self._contents` assigned only in `compose`, undeclared in `__init__`
- **Location:** `compose` line 77 / `add_tool` line 83; `__init__` lines 60–69
- **Issue:** `self._contents` is created only in `compose` but read in `add_tool`;
  a checker has no declared type and a pre-compose call would `AttributeError`.
- **Recommendation:** Declare in `__init__`:
  `self._contents: Collapsible.Contents | None = None` (keep the real assignment
  in `compose`).
- **Sources:** https://peps.python.org/pep-0008/

### 🖼️ Textual — MINOR: `compose` override relies on `Collapsible` private internals
- **Location:** lines 71–80
- **Issue:** The override caches the inner container and reaches into private
  internals (`self._title`, `self._contents_list`, `self.Contents`); a Textual
  upgrade could break it. Cached references are also detached by a recompose
  (unused here, so not an active bug — fragile).
- **Recommendation:** Prefer `query_one(Collapsible.Contents)` to fetch the
  container on demand in `add_tool`, or pin the Textual version.

### Nits
- `tool_preview` line 13: the `isinstance(block.input, dict)` guard is dead under
  the SDK's `dict[str, Any]` type — drop it or comment the intentional distrust.
- `_format_input` line 22: `data: object` is broader than the actual `dict[str,
  Any]` caller — narrow it (or note it's intentionally generic).
- `_summary` lines 96–97: magic numbers `47`/`48` with an unexplained off-by-one;
  hoist to a named constant and slice consistently.

---

## Suggested fix batch

1. **Security majors (1 & 2)** + **SDK major** — fix together with the deferred
   `renderer.py` markup-escape sink and `ServerToolUseBlock` dispatch (one
   coherent untrusted-tool-rendering hardening pass). Add an escaping/`Content`
   helper used by both card titles; widen type surface + renderer dispatch.
2. **Efficiency major** — replace `Markdown` with `Static(Syntax(...))`; this
   also removes the code-fence-breakout minor for free.
3. **Python/Textual minors + nits** — annotations, `_contents` declaration,
   on-demand `query_one`, named constant — low-risk cleanup batched with the above.
