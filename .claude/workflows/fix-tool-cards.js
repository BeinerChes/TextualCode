export const meta = {
  name: 'fix-tool-cards',
  description: 'Fix tool_cards.py + renderer.py review findings (Sonnet fixer -> test-writer -> adversarial reviewer with pushback, up to 2 refix rounds per task)',
  phases: [
    { title: 'T1: Untrusted-tool-rendering hardening (tool_cards.py, renderer.py)', model: 'sonnet' },
    { title: 'T2: Efficiency — Markdown -> Static/Syntax (tool_cards.py)', model: 'sonnet' },
    { title: 'T3: Python/Textual minors + nits (tool_cards.py)', model: 'sonnet' },
  ],
}

const REPO = 'C:\\\\Users\\\\beine\\\\source\\\\repos\\\\TerminalBrowser\\\\TextualCode'

const PREAMBLE = `You are working in the TextualCode project (Textual TUI wrapping the Claude Agent SDK), repo root ${REPO}.
MANDATORY before doing anything:
1. Read ${REPO}\\.claude\\state.md
2. Read ${REPO}\\.claude\\lessons\\INDEX.md and open any lesson relevant to your change (esp. quarantine-untrusted-input-via-sentinel-fence, dont-interpolate-raw-fields-into-logs, escape-untrusted-cli-output-before-markup, verify-widget-apis-against-installed-source, offload-blocking-io-from-event-loop).
PROJECT RULE — never guess an API: verify SDK/framework behavior against the installed claude-agent-sdk==0.2.88 and Textual==8.2.7 (read their source under .venv if needed) and/or a web search of official Anthropic/Textual docs BEFORE relying on a name or behavior. Cite what you checked.
Do not touch .claude/state.md or .claude/lessons/ (read-only; harvester-owned).
The full review with sources is at ${REPO}\\reviews\\tool_cards.py.md.`

const REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['approved', 'assessment', 'tests_pass', 'issues'],
  properties: {
    approved: { type: 'boolean', description: 'true ONLY if every targeted finding is correctly fixed, no regression introduced, and tests pass' },
    assessment: { type: 'string' },
    tests_pass: { type: 'string', enum: ['pass', 'fail', 'not-run'], description: 'result of running the task tests via uv run pytest' },
    import_ok: { type: 'boolean', description: 'whether `uv run python -c "import textualcode.app"` still succeeds' },
    issues: {
      type: 'array',
      description: 'Required changes when not approved (empty if approved). Be specific and actionable.',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'location', 'problem', 'required_change'],
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          location: { type: 'string' },
          problem: { type: 'string' },
          required_change: { type: 'string' },
        },
      },
    },
  },
}

const TASKS = [
  {
    id: 'T1',
    phase: 'T1: Untrusted-tool-rendering hardening (tool_cards.py, renderer.py)',
    files: 'textualcode/tool_cards.py, textualcode/renderer.py',
    testFile: 'tests/test_tool_cards_security.py',
    fix: `FIX these review findings in ${REPO}\\textualcode\\tool_cards.py and ${REPO}\\textualcode\\renderer.py (ONLY these two files):

1. [SECURITY major — CWE-150] ToolCard title markup-injection / MarkupError DoS (tool_cards.py line ~43). The title f-string \`f"🔧 {block.name}  {tool_preview(...)}"\` passes model/MCP-controlled \`block.name\` and the \`tool_preview()\` output as a raw str to Collapsible. In Textual 8.2.7, Collapsible -> CollapsibleTitle calls Content.from_text(label) with markup=True, so a tool name/preview containing \`[\` is parsed as Textual content markup (style/link injection) or raises MarkupError (crashing the card render = DoS). FIX: neutralize the dynamic, model-controlled segments. Match the existing in-repo pattern — \`from rich.markup import escape\` and escape block.name and the tool_preview() result before interpolation (see screens.py which uses escape(...), and workspace_panel._escape). The static emoji/literal parts may stay. VERIFY against installed Textual 8.2.7 source (textual/widgets/_collapsible.py, textual/content.py from_text default markup=True) that titles are markup-parsed.

2. [SECURITY major — CWE-150] ToolGroupCard summary markup sink (tool_cards.py: _summary lines ~92-98, assigned to self.title at line ~90). \`_summary()\` joins model-controlled block.name values into self.title, which Collapsible._watch_title -> CollapsibleTitle -> Content.from_text(markup=True) parses as markup. Same injection/DoS. FIX: escape each name (rich.markup.escape) before joining, using the SAME helper/approach as finding 1 so both the per-card and aggregated paths are covered.

3. [SDK major] ServerToolUseBlock silently dropped (tool_cards.py imports/annotations + renderer.py dispatch line ~57). In claude-agent-sdk 0.2.88, ServerToolUseBlock (server-executed tools: web_search, web_fetch, code_execution, bash_code_execution, text_editor_code_execution, advisor, tool_search_*) is a SEPARATE dataclass whose MRO is (ServerToolUseBlock, object) — it is NOT a subclass of ToolUseBlock. So renderer._render_assistant's \`isinstance(block, ToolUseBlock)\` at line ~57 is False for server-tool blocks and they NEVER reach ToolGroupCard/ToolCard (silently dropped from the UI). FIX: (a) in renderer.py import ServerToolUseBlock from claude_agent_sdk and widen the dispatch to \`isinstance(block, (ToolUseBlock, ServerToolUseBlock))\`; (b) in tool_cards.py import ServerToolUseBlock and widen the type annotations on tool_preview(block), ToolCard.__init__(block), and ToolGroupCard.add_tool(block) to \`ToolUseBlock | ServerToolUseBlock\`. The bodies only read the shared id/name/input fields, so NO body logic changes are needed. VERIFY ServerToolUseBlock is exported by claude_agent_sdk 0.2.88 and confirm its MRO (it is a distinct dataclass with id/name/input). Confirm AskUserQuestion special-casing in renderer.py still applies only to client-side ToolUseBlock (server tools have no AskUserQuestion name, so behavior is unchanged).

DO NOT address the Markdown code-fence-breakout body minor in this task — a separate task replaces the Markdown widget with Static+Syntax, which removes that sink entirely. Touch ONLY the title/summary markup sinks and the ServerToolUseBlock dispatch/annotations here.
Do NOT change any other behavior. Preserve all existing comments' intent.`,
    test: `WRITE pytest tests in ${REPO}\\tests\\test_tool_cards_security.py. pytest + pytest-asyncio are installed (asyncio_mode=auto). Keep tests hermetic (no network, no live SDK). Cover:
- A ToolUseBlock whose name contains markup metacharacters (e.g. name="evil[red]bold[/]", and an unmatched-bracket case like "x[") can be turned into a ToolCard title WITHOUT raising MarkupError, and the resulting title is markup-safe (assert the dynamic part is escaped — e.g. via rich.markup.escape on the same input, or assert Content.from_markup/Text.from_markup of the title does not raise). Construct ToolUseBlock(id=..., name=..., input={...}).
- ToolGroupCard._summary with malicious names (a name containing "[") produces a markup-safe title that does not raise when parsed as markup.
- renderer dispatch: build a MessageRenderer (inspect renderer.py + config.Settings for construction; use a minimal Settings and a fake/minimal ConversationView stub exposing the awaited methods add_message/add_widget). Feed an AssistantMessage whose content contains a ServerToolUseBlock and assert it is rendered (a ToolGroupCard is created/added and add_tool is invoked for the server block) — i.e. it is NOT dropped. Also assert a normal ToolUseBlock still routes the same way and AskUserQuestion is still skipped as a card.
- Confirm ServerToolUseBlock is importable from claude_agent_sdk and is not a subclass of ToolUseBlock (regression guard documenting WHY the dispatch must list both).
Fix only the test file to make tests pass; if you think the source is wrong, note it for the reviewer instead of editing source. Run 'uv run pytest tests/test_tool_cards_security.py -q' until green; report the result.`,
  },
  {
    id: 'T2',
    phase: 'T2: Efficiency — Markdown -> Static/Syntax (tool_cards.py)',
    files: 'textualcode/tool_cards.py',
    testFile: 'tests/test_tool_cards_render.py',
    fix: `FIX this efficiency finding in ${REPO}\\textualcode\\tool_cards.py (ONLY this file):
[EFFICIENCY major] ToolCard.__init__ (lines ~42-49, import line ~8) renders each tool call's static JSON by wrapping it in a Textual Markdown widget (\`Markdown(f"\\\`\\\`\\\`json\\n{body}\\n\\\`\\\`\\\`")\`). Markdown is the heaviest text widget in Textual: each block becomes its own child widget and Markdown.update() instantiates a fresh MarkdownIt("gfm-like") parser and parses the whole string on every mount (verified in installed textual 8.2.7). The content is pre-formatted, non-streaming JSON needing only highlighted display. FIX: render the JSON with a single lightweight Static containing a Rich Syntax object — \`from rich.syntax import Syntax\` and \`from textual.widgets import Static\`, then \`Static(Syntax(body, "json", word_wrap=True))\`. Remove the now-unused Markdown import. This also ELIMINATES the markdown code-fence-breakout security minor (no more \\\`\\\`\\\`json fence), so _format_input no longer needs fence sanitization. VERIFY Static accepts a Rich renderable and Syntax's constructor signature against installed Textual 8.2.7 + Rich source/docs (confirm the "json" lexer and word_wrap kwarg). Keep _format_input's truncation logic as-is. Do NOT change any other behavior.`,
    test: `WRITE pytest tests in ${REPO}\\tests\\test_tool_cards_render.py (hermetic, no network). Cover:
- ToolCard constructs successfully and its rendered body is a Static wrapping a Rich Syntax object (not a Markdown widget). Inspect the composed children or the renderable; assert no textual.widgets.Markdown instance is used. (You may need to query the card's children — construct it and inspect; or assert on the widget type passed to super().__init__ by checking the child node.)
- The JSON body still reflects _format_input output (e.g. a known input dict appears, truncation marker present when over the limit).
- A tool input containing a literal triple-backtick run no longer causes a markdown fence breakout (since Markdown is gone) — i.e. the content is rendered verbatim by Syntax.
Run 'uv run pytest tests/test_tool_cards_render.py -q' until green; fix only the test file if needed; report the result.`,
  },
  {
    id: 'T3',
    phase: 'T3: Python/Textual minors + nits (tool_cards.py)',
    files: 'textualcode/tool_cards.py',
    testFile: 'tests/test_tool_cards_quality.py',
    fix: `FIX these minor/nit findings in ${REPO}\\textualcode\\tool_cards.py (ONLY this file). These are low-risk quality cleanups — do NOT change runtime behavior:
1. [PYTHON/TEXTUAL minor] ToolGroupCard.compose (line ~71) override lacks a return annotation. Add \`-> ComposeResult\` and \`from textual.app import ComposeResult\` (matches the base Collapsible.compose signature in Textual 8.2.7).
2. [PYTHON minor] self._contents is assigned only inside compose (line ~77) but read in add_tool (line ~83). Declare it in __init__ with a forward type: \`self._contents: Collapsible.Contents | None = None\` (keep the real assignment in compose). Do not otherwise change compose's behavior.
3. [PYTHON/STYLE nit] _summary (lines ~96-97) uses bare magic numbers 47/48 with an unexplained off-by-one. Hoist to a named module-level constant (e.g. _SUMMARY_NAME_LIMIT = 48) and slice consistently (names[: _SUMMARY_NAME_LIMIT - 1] + "…").
4. [PYTHON nit] tool_preview line ~13: the \`isinstance(block.input, dict)\` guard is dead under the SDK's dict[str, Any] type. Either drop it and use block.input directly, OR keep it and add a one-line comment explaining the intentional defensive distrust of SDK shape. Pick whichever is cleaner; prefer keeping a documented guard if it's defensive-by-design.
5. [PYTHON nit] _format_input line ~22: \`data: object\` is broader than the actual dict[str, Any] caller. Narrow to \`data: dict[str, Any]\` (import Any from typing) OR add a comment that it's intentionally generic/JSON-serializable. Prefer narrowing.
NOTE: tasks T1 and T2 already modified this file (escaping helper, Static/Syntax body, possibly widened annotations to ToolUseBlock | ServerToolUseBlock). Read the CURRENT file first and integrate cleanly without reverting their changes.`,
    test: `WRITE pytest tests in ${REPO}\\tests\\test_tool_cards_quality.py (hermetic). Cover:
- _summary truncates at the named constant boundary (names list whose joined length exceeds the cap is truncated with the ellipsis; under the cap is untouched). Assert the constant exists and is used.
- _format_input: dict -> pretty JSON; truncation adds the "(truncated)" marker past the limit; the json.dumps fallback path (pass a non-JSON-serializable object) yields str(data).
- tool_preview: returns the first matching preview key's first line capped at 60 chars with ellipsis; returns "" when no key matches.
- ToolGroupCard instantiates with self._contents declared (None before compose).
Run 'uv run pytest tests/test_tool_cards_quality.py -q' until green; fix only the test file if needed; report the result.`,
  },
]

const results = []

for (const task of TASKS) {
  phase(task.phase)

  // Round 1: fix
  await agent(
    `${PREAMBLE}\n\nROLE: FIXER (implement the changes precisely).\n\n${task.fix}\n\nAfter editing, run 'uv run python -c "import textualcode.app"' to confirm the package still imports. Report exactly what you changed, file+line, and what you verified about the SDK/Textual APIs.`,
    { model: 'sonnet', label: `fix:${task.id}`, phase: task.phase }
  )

  // Test writer
  await agent(
    `${PREAMBLE}\n\nROLE: TEST WRITER. The fixes for task ${task.id} (${task.files}) were just applied.\n\n${task.test}\n\nFix ONLY the test file (not the source — if you believe the source is wrong, note it for the reviewer instead of changing it). Report the final pytest result.`,
    { model: 'sonnet', label: `test:${task.id}`, phase: task.phase }
  )

  // Reviewer with pushback (+ up to 2 refix rounds)
  let verdict = null
  for (let round = 1; round <= 3; round++) {
    verdict = await agent(
      `${PREAMBLE}\n\nROLE: ADVERSARIAL REVIEWER — push back hard. Task ${task.id} touched: ${task.files}. Tests in ${task.testFile}.\n\nDo ALL of:\n- Run 'git diff -- ${task.files} ${task.testFile}' and read the changed source files in full.\n- Verify EVERY targeted finding for this task is actually and correctly fixed (re-read the task spec below).\n- Verify NO behavior regression and no over-reach (e.g. a feature gutted, isolation weakened, a real API misused, escaping that double-escapes or breaks normal titles). Web-verify any SDK/Textual claim against official docs / installed source.\n- Run 'uv run pytest ${task.testFile} -q' and record pass/fail. Judge whether the tests are MEANINGFUL (the security/dispatch behavior is actually asserted), not just present.\n- Run 'uv run python -c "import textualcode.app"' and record import_ok.\nApprove ONLY if all findings are correctly fixed, no regression, and tests meaningfully pass. Otherwise set approved=false with specific required_change items.\n\nTASK SPEC UNDER REVIEW:\n${task.fix}`,
      { model: 'sonnet', label: `review:${task.id}#${round}`, phase: task.phase, schema: REVIEW_SCHEMA }
    )
    if (verdict.approved || round === 3) break
    // Refix addressing the reviewer's issues
    await agent(
      `${PREAMBLE}\n\nROLE: FIXER (round ${round + 1}). The adversarial reviewer REJECTED the changes for task ${task.id} (${task.files}, tests ${task.testFile}). Address EVERY issue below, editing source and/or tests as needed. Then run 'uv run pytest ${task.testFile} -q' and 'uv run python -c "import textualcode.app"'.\n\nREVIEWER ISSUES:\n${JSON.stringify(verdict.issues, null, 2)}`,
      { model: 'sonnet', label: `refix:${task.id}#${round}`, phase: task.phase }
    )
  }

  results.push({ task: task.id, files: task.files, verdict })
}

return { results }
