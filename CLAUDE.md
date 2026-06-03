# TextualCode — Project Guidance

## Working rules

- **MANDATORY — READ `.claude/state.md` FIRST.** Before anything else at the
  start of every session/task — for the main agent AND any subagent you spawn —
  open `.claude/state.md`. It is the carried-over session state (goal, what was
  done, mistakes/corrections, result, and what's next). This is not optional and
  takes precedence over all other steps; read it before the lessons index, before
  touching any code, before responding to the task. When delegating, tell the
  subagent in its prompt to read `.claude/state.md` first, since built-in
  **Explore**/**Plan** subagents do not load CLAUDE.md.

- **NEVER write `.claude/state.md` yourself — only read it.** That file is
  owned and maintained by the harvester; it is carried-over state, not a
  scratchpad for you to update. Do not create, edit, overwrite, or "update to
  reflect this work" `.claude/state.md` (and do not direct a subagent to). Your
  only interaction with it is reading it at the start of a task. The same goes
  for `.claude/lessons/` — read it; the harvester writes it.

- **Read the lessons index first.** At the start of every task — for the main
  agent AND any subagent you spawn — open `.claude/lessons/INDEX.md` before
  doing anything else. It is a one-line-per-lesson map of hard-won rules from
  past sessions. Then, based on the task at hand, open the specific lesson
  file(s) whose rule applies and follow them. Do not skip this; these lessons
  exist because the mistake already happened once.
  - When delegating to a subagent, tell it in its prompt to read
    `.claude/lessons/INDEX.md` and the relevant lesson(s) — the built-in
    **Explore** and **Plan** subagents do not load CLAUDE.md, so they will not
    see this rule unless you state it explicitly.

- **Never guess an API.** Before implementing a fix or addition that depends on
  how a library/framework behaves, verify it. The order is fixed:
  1. **Check the installed version first.** Determine the exact version of the
     package in use (e.g. `pip show <pkg>` / read the lockfile) so verification
     targets that version, not whatever a search happens to surface.
  2. **Web search is the primary verification method.** Look it up online against
     authoritative docs — **prefer Anthropic's official documentation and
     repos** for anything Claude/Agent-SDK-related; otherwise the library's
     official docs or **GitHub** repo (source, docstrings, issues). Scope the
     search to the installed version from step 1.
  3. **Reading the installed source under `.venv` is the fallback** (second
     option) — use it only when a web search can't confirm the behavior, and say
     so when you do.
  - **If the installed version is outdated / not the latest, propose upgrading**
     before building on old behavior — surface the newer version and what it
     changes, and let the user decide.
  - Reasoning from memory never counts. Always cite what you checked (and the
     version it applies to).
