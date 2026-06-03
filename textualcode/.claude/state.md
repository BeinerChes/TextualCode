# Session State

_Structured map (goal · did · mistakes · result · next · keywords) for the next
agent. Written by the second Opus session co-working on TextualCode — read this
before editing, we share these files._

## Goal

Add user-requested features to TextualCode (the Claude-Code-style TUI on the
Agent SDK): drag-drop file input, an animated "thinking" indicator, and — the
main one this session — render the **`AskUserQuestion`** tool as an interactive
form instead of a raw JSON card.

## Did

- **AskUserQuestion → interactive form (NEW — you don't know about this).**
  Touched 6 files: `agent.py`, `screens.py`, `app.py`, `config.py`, `app.tcss`,
  `renderer.py`.
  - `agent.py`: `_approve_tool` intercepts `tool_name == "AskUserQuestion"` →
    new `question_handler` → returns
    `PermissionResultAllow(updated_input={"questions", "answers"})`.
  - `screens.py`: `QuestionForm` modal — `RadioSet` per single-select question,
    `SelectionList` for `multiSelect`.
  - `app.py`: `_ask_question` (push_screen + Future bridge); wired
    `question_handler=self._ask_question` into `AgentSession(...)`.
  - `config.py`: `AskUserQuestion` added to `BUILTIN_TOOLS`.
  - `renderer.py`: skips the raw AskUserQuestion tool card (form is the UI).
- **Drag-drop file input** (`PromptInput`) + **ThinkingBar** (animated star +
  gerund + elapsed) — committed earlier on `master`.
- **Ctrl+V duplicate fix**: `PromptInput.action_paste` is a no-op (terminal
  already delivers a bracketed paste → `_on_paste`). Uncommitted.
- **Left your `/compact` harvest feature (harvest/lessons/transcript/prompts)
  completely untouched.**

## Mistakes

- I first told the user AskUserQuestion "can't feed an answer back through the
  SDK". **Wrong.** A websearch + the official docs
  (code.claude.com/docs/en/agent-sdk/user-input) show it routes through the same
  `can_use_tool` callback; the answer goes back via `updated_input["answers"]`
  (maps question text → chosen label, or array for multiSelect). Corrected.

## Result

- App imports + mounts clean. AskUserQuestion form verified headless: single
  answer, multi answer, and cancel→None all correct; agent intercept returns the
  right `updated_input`.
- **Uncommitted** (master): the AskUserQuestion 6-file change + the action_paste
  fix + your harvest files (`harvest.py`, `lessons.py`, `transcript.py`,
  `prompts.py` are still untracked). Nothing of mine is committed yet — user is
  testing first.

## Next

- User to test the AskUserQuestion form live (plan-style prompts trigger it).
- Deferred: suppress per-card usage on **workflow** sub-agent cards (SDK reports
  cumulative usage, not per-agent — confirmed via task-debug.log).
- Deferred: live token streaming (`include_partial_messages`) → live `↓ tokens`
  in ThinkingBar + streaming response text.
- Drag-drop itself may not fire on this terminal (only Ctrl+V does); terminal-
  dependent, parked.

## Coordination

We both edit `app.py` / `widgets.py`. If files look unexpectedly changed, that's
the other session. Confirm who's driving before large edits. Gotchas live in
`HANDOFF.md` (root) — esp.: never name a widget method `_render` (shadows Textual
internals); permission/question dialogs use `push_screen`+`Future` not
`push_screen_wait` (SDK calls the callback off-worker).

## Keywords

AskUserQuestion · can_use_tool · updated_input · QuestionForm · RadioSet ·
SelectionList · question_handler · ThinkingBar · PromptInput · action_paste ·
harvest/compact · workflow cumulative usage · push_screen+Future
