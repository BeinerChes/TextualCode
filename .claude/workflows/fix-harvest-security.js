export const meta = {
  name: 'fix-harvest-security',
  description: 'Fix CRITICAL slug path-traversal + make is_error load-bearing (Sonnet fixer -> test-writer -> reviewer with pushback)',
  phases: [
    { title: 'Fix harvest security', model: 'sonnet' },
  ],
}

const REPO = 'C:\\\\Users\\\\beine\\\\source\\\\repos\\\\TerminalBrowser\\\\TextualCode'

const PREAMBLE = `You are working in the TextualCode project (Textual TUI wrapping the Claude Agent SDK), repo root ${REPO}.
MANDATORY before doing anything:
1. Read ${REPO}\\.claude\\state.md
2. Read ${REPO}\\.claude\\lessons\\INDEX.md and open lessons relevant to your change (esp. byte-identical-user-output-verification, escape-untrusted-cli-output-before-markup).
PROJECT RULE — never guess an API: verify against installed claude-agent-sdk==0.2.88 source / official docs. Cite what you checked.
Do not touch .claude/state.md or .claude/lessons/ content (read-only; harvester-owned) — but you MAY edit textualcode/lessons.py (the writer module).`

const REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['approved', 'assessment', 'tests_pass', 'import_ok', 'issues'],
  properties: {
    approved: { type: 'boolean' },
    assessment: { type: 'string' },
    tests_pass: { type: 'string', enum: ['pass', 'fail', 'not-run'] },
    import_ok: { type: 'boolean' },
    issues: {
      type: 'array',
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

const FIX = `FIX these reviewed findings. Edit ONLY textualcode/harvest.py, textualcode/lessons.py, textualcode/harvest_controller.py (and tests).

1) [CRITICAL — CWE-22 path traversal / arbitrary file write] In harvest.py _parse (~L145), the model-controlled lesson slug is used verbatim when non-empty; _slugify (restricts to [a-z0-9-], collapses runs, strips hyphens, caps length) is applied ONLY as the empty fallback. The slug flows to lessons.py _write_lessons (~L86) as 'lessons_dir / f"{slug}.md"' and write_text()s model-authored content -> a slug like "../../../../foo" writes OUTSIDE .claude/lessons/.
   - Fix at the SOURCE boundary: ALWAYS normalize the slug through _slugify, e.g.
       cand = _slugify(str(item.get("slug") or ""))
       slug = cand if cand != "lesson" else _slugify(rule)
   - Defense-in-depth at the SINK (lessons.py _write_lessons): before writing, resolve the path and confine it:
       full = (lessons_dir / f"{lesson.slug}.md").resolve()
       if not full.is_relative_to(lessons_dir.resolve()): skip this lesson (continue) — do not write outside the dir.
     (Use pathlib.Path.is_relative_to, available in 3.11.)

2) [MINOR — markdown/index injection] In harvest.py _parse, model text fields can contain newlines / markdown metacharacters that corrupt INDEX.md (category becomes '## {category}', rule becomes a list line). Constrain at the parse boundary: collapse embedded whitespace/newlines to single spaces and cap length for single-line fields — category (<=40 chars, single line), satisfied (single line), and rule (single line, <=300 chars). Do NOT change the JSON parsing semantics otherwise.

3) [MAJOR — is_error not load-bearing] harvest.py already sets HarvestResult.is_error, but harvest_controller.run writes files and reports success regardless. In harvest_controller.run, AFTER the Harvester call returns, if result.is_error is True: stop the thinking bar (key="harvest"), report a clear error via report_error or add_markdown (e.g. an SDK error / budget or turn cap was hit), and RETURN WITHOUT calling write_harvest and WITHOUT the success message. PRESERVE all existing user-visible strings on the success path byte-identically (see lesson byte-identical-user-output-verification) — only ADD a new error branch.

After editing run 'uv run python -c "import textualcode.app"'. Report exactly what changed and what you verified.`

const TEST = `WRITE/EXTEND pytest tests (pytest + pytest-asyncio installed, asyncio_mode=auto):
- harvest slug sanitization: feed _parse (or Harvester._parse) JSON whose lesson slug is "../../../foo", "/etc/passwd", "a/b\\\\c", "..\\\\..\\\\x" and assert the resulting Lesson.slug matches ^[a-z0-9-]+$ (no slashes, dots, drive letters). Include a normal slug passes through unchanged.
- lessons.py path confinement: call write_harvest/_write_lessons (use a tmp_path project dir) with a Lesson whose slug somehow contains traversal (construct the Lesson directly) and assert NO file is written outside the lessons dir (the function skips it) and no exception escapes.
- single-line constraint: category/rule containing embedded newlines come back single-line and length-capped.
- is_error load-bearing: assert harvest_controller.run does NOT call write_harvest and does NOT emit the success message when result.is_error is True (monkeypatch Harvester.run to return a HarvestResult(is_error=True); stub the app/conversation; assert write_harvest not invoked). Also assert the success path still calls write_harvest when is_error is False.
Run 'uv run pytest -q' and iterate until ALL pass. Report the final result.`

phase('Fix harvest security')

await agent(`${PREAMBLE}\n\nROLE: FIXER.\n\n${FIX}`, { model: 'sonnet', label: 'fix:harvest-sec', phase: 'Fix harvest security' })

await agent(`${PREAMBLE}\n\nROLE: TEST WRITER. The harvest security fixes were just applied.\n\n${TEST}`, { model: 'sonnet', label: 'test:harvest-sec', phase: 'Fix harvest security' })

let verdict = null
for (let round = 1; round <= 3; round++) {
  verdict = await agent(
    `${PREAMBLE}\n\nROLE: ADVERSARIAL REVIEWER — push back hard. Files: textualcode/harvest.py, textualcode/lessons.py, textualcode/harvest_controller.py + tests.\n\nDo ALL of:\n- 'git diff -- textualcode/harvest.py textualcode/lessons.py textualcode/harvest_controller.py tests/' and read changed files in full.\n- Verify the CRITICAL traversal is closed BOTH at source (_slugify always applied) AND sink (is_relative_to confinement). Try to think of a slug that still escapes (absolute paths, drive letters C:\\\\, UNC \\\\\\\\host, leading slash, dot segments) — confirm each is neutralized.\n- Verify is_error now blocks write_harvest + success message, and that EXISTING success-path strings are byte-identical (lesson byte-identical-user-output-verification).\n- Verify single-line/length caps on category/rule; verify JSON parsing otherwise unchanged.\n- Run 'uv run pytest -q' (record pass/fail; judge meaningfulness — traversal cases actually asserted) and 'uv run python -c "import textualcode.app"' (import_ok).\nApprove ONLY if the critical is fully closed, is_error is load-bearing, no regression/string drift, and tests meaningfully pass. Else approved=false with specific required_change items.\n\nSPEC:\n${FIX}`,
    { model: 'sonnet', label: `review:harvest-sec#${round}`, phase: 'Fix harvest security', schema: REVIEW_SCHEMA }
  )
  if (verdict.approved || round === 3) break
  await agent(
    `${PREAMBLE}\n\nROLE: FIXER (round ${round + 1}). The reviewer REJECTED the changes. Address EVERY issue, then 'uv run pytest -q' and 'uv run python -c "import textualcode.app"'.\n\nISSUES:\n${JSON.stringify(verdict.issues, null, 2)}`,
    { model: 'sonnet', label: `refix:harvest-sec#${round}`, phase: 'Fix harvest security' }
  )
}

return { verdict }
