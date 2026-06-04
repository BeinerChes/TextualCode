export const meta = {
  name: 'file-review',
  description: 'Deep multi-agent code review of a single Python file (general+SDK/Textual+efficiency+security, each web-search-backed)',
  phases: [
    { title: 'Review' },
    { title: 'Synthesize' },
  ],
}

// args = { path, name, sdk: bool, textual: bool } (may arrive as a JSON string)
const cfg = typeof args === 'string' ? JSON.parse(args) : args
if (!cfg || !cfg.path) {
  throw new Error('file-review: missing args.path; received ' + JSON.stringify(args))
}
const path = cfg.path
const fileName = cfg.name
const isSdk = !!cfg.sdk
const isTextual = !!cfg.textual

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['summary', 'findings'],
  properties: {
    summary: { type: 'string', description: 'One-paragraph overall assessment for this dimension' },
    websearch: { type: 'string', description: 'What best-practice sources were searched and the key takeaway (with URLs)' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'location', 'issue', 'recommendation'],
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor', 'nit'] },
          location: { type: 'string', description: 'Line number(s) or function/class name' },
          issue: { type: 'string' },
          recommendation: { type: 'string' },
          sources: { type: 'array', items: { type: 'string' }, description: 'URLs of authoritative sources backing this finding' },
        },
      },
    },
  },
}

const PROJECT_PREAMBLE = `You are reviewing a single file in the TextualCode project (a Textual-based terminal UI wrapping the Claude Agent SDK).
MANDATORY project rules before reviewing:
1. Read C:\\Users\\beine\\source\\repos\\TerminalBrowser\\TextualCode\\.claude\\state.md
2. Read C:\\Users\\beine\\source\\repos\\TerminalBrowser\\TextualCode\\.claude\\lessons\\INDEX.md and open any lesson directly relevant to your review dimension.
Then read the target file in full: ${path}

You MUST perform a real WebSearch for current best practices relevant to your review dimension BEFORE forming findings, and cite the URLs you used in each finding's "sources" and in the "websearch" field. Do not rely on memory alone.
Report concrete, line-anchored findings only. Do not invent issues; if the file is clean on your dimension, return an empty findings array with a summary saying so.`

const dimensions = []

dimensions.push({
  key: 'python',
  label: `py:${fileName}`,
  prompt: `${PROJECT_PREAMBLE}

YOUR DIMENSION: General Python best practices.
Web-search current authoritative Python guidance (PEP 8 / PEP 484 typing, idiomatic patterns, error handling, naming, structure, docstrings, modern Python 3.11+ features) and review ${path} against it. Focus on correctness-adjacent quality, readability, typing, exception handling, resource management, and idiomatic structure. Do NOT cover efficiency or security (other agents own those).`,
})

if (isSdk) {
  dimensions.push({
    key: 'sdk',
    label: `sdk:${fileName}`,
    prompt: `${PROJECT_PREAMBLE}

YOUR DIMENSION: Claude Agent SDK correctness.
This file imports the Claude Agent SDK. Web-search Anthropic's OFFICIAL Claude Agent SDK documentation and GitHub repo for the patterns used here (ClaudeSDKClient / query, ClaudeAgentOptions, message/streaming types, tool & permission handling, session/setting_sources, cost/usage fields). Verify the SDK is used correctly and idiomatically against the official docs for the installed version. Flag misuse, deprecated patterns, incorrect option names, wrong message-shape assumptions, missing cleanup, and missed SDK features. Cite Anthropic docs/GitHub URLs.`,
  })
}

if (isTextual) {
  dimensions.push({
    key: 'textual',
    label: `tx:${fileName}`,
    prompt: `${PROJECT_PREAMBLE}

YOUR DIMENSION: Textual framework correctness.
This file imports Textual. Web-search the OFFICIAL Textual documentation and GitHub repo for the APIs used here (widgets, reactives, watchers, @work workers/threading, messages, compose/mount lifecycle, CSS, screens, event handling & prevent_default vs stop). Verify correct, idiomatic, thread-safe Textual usage. Flag UI-thread blocking, reactive misuse, worker/threading mistakes, event-handling bugs, and lifecycle issues. Cite Textual docs/GitHub URLs.`,
  })
}

dimensions.push({
  key: 'efficiency',
  label: `eff:${fileName}`,
  prompt: `${PROJECT_PREAMBLE}

YOUR DIMENSION: Efficiency / performance.
Web-search current best practices for the performance-relevant constructs in this file (data structures, loops, I/O, subprocess use, repeated work, caching, async vs thread offloading, allocations). Ask: is this the most efficient reasonable approach? Flag avoidable O(n^2), redundant recomputation, unbatched I/O, blocking calls that should be offloaded, and inefficient data structures. Cite sources. Do NOT cover style or security.`,
})

dimensions.push({
  key: 'security',
  label: `sec:${fileName}`,
  prompt: `${PROJECT_PREAMBLE}

YOUR DIMENSION: Security.
Web-search current security best practices relevant to this file (command/subprocess injection, path traversal, untrusted CLI/git output, secret handling, unsafe deserialization, markup/escaping, permission scoping). Flag concrete vulnerabilities and unsafe patterns with severity. Cite OWASP/CWE/official sources. Do NOT cover style or efficiency.`,
})

phase('Review')
const results = await parallel(
  dimensions.map((d) => () =>
    agent(d.prompt, { label: d.label, phase: 'Review', schema: FINDINGS_SCHEMA })
      .then((r) => ({ dimension: d.key, result: r }))
  )
)

const collected = results.filter(Boolean).filter((r) => r.result)

phase('Synthesize')
return {
  file: fileName,
  path,
  dimensions: dimensions.map((d) => d.key),
  reviews: collected,
}
