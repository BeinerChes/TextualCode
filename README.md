# TextualCode

A Claude-Code-style terminal UI built with [Textual](https://textual.textualize.io/),
driving the official [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk).
Header, scrollable conversation, and an input box — assistant text and tool calls
stream into the UI live.

## Design principle: no extra token spend

**We can't afford to spend more tokens than the Claude Code CLI itself.**

TextualCode is a UI *around* the Agent SDK — it must add **zero** billed token
overhead beyond the conversation the user actually asked for. Concretely:

- ✅ **Allowed:** local/free operations — rendering, the stats panel, and
  `get_context_usage()` (a *local* control request to the CLI, no message sent,
  no tokens billed).
- ❌ **Not allowed:** any feature that silently makes extra model calls — e.g.
  auto-summarising with a side LLM call, background "analysis" turns, or
  speculative prefetching. If a feature needs the model, it must be an explicit
  user action.

When in doubt, prefer deterministic/local logic (head/tail summaries, token
math from the `usage` the SDK already returns) over an extra API round-trip.

## Auth

It uses whatever the **Claude Code CLI** is logged in with — your Pro/Max
subscription or an `ANTHROPIC_API_KEY`. Nothing is hard-coded. Install and log in
the CLI first (`claude` then `/login`).

## Run

Uses [uv](https://docs.astral.sh/uv/) for dependency and environment management.

```powershell
# from the TextualCode folder
uv sync                      # create .venv and install deps
uv run python -m textualcode # launch the app
```

`uv sync` reads `pyproject.toml`; no manual venv activation needed.

## Project layout

The app is split into single-responsibility modules under `textualcode/`:

| Module | Responsibility |
|---|---|
| `config.py` | Settings + model-alias resolution (pure data) |
| `agent.py` | `AgentSession` — owns the Agent SDK connection (UI-agnostic) |
| `stats.py` | `UsageStats` — accumulates per-turn token/cost usage |
| `widgets.py` | `ConversationView`, `ToolCard`, `StatsPanel`, `TaskPanel` |
| `commands.py` | `CommandRouter` — parse/dispatch `/slash` commands |
| `permissions.py` | `PermissionPolicy` — tiered auto-allow + session memory |
| `screens.py` | `PermissionDialog`, `ToolSelector`, `ModelSelector` — modals |
| `widgets.py` | `ConversationView`, `ToolCard`, `StatsPanel` — presentation |
| `renderer.py` | `MessageRenderer` — SDK messages → conversation widgets |
| `app.py` | `TextualCodeApp` — wiring only; composes the above |
| `app.tcss` | Styling, kept out of Python |

## Tools & permissions

The model has the **full Claude Code toolset** (shell, file read/write/edit,
search, …) — these are well-tuned by Anthropic, so we use them as-is rather than
reinventing them.

Permissions follow a **tiered policy** (`permissions.py`, modeled on Claude
Code's own rules — deny > ask > allow, Bash prefix matching, shell-operator
awareness):

- **Auto-allowed** (no prompt): read-only/safe tools — `Read`, `Glob`, `Grep`,
  `TodoWrite`.
- **Ask** (everything else): a **`PermissionDialog`** with three choices —
  **Approve once (a)**, **Approve similar (s)**, **Deny (d)** (Esc denies).
- **Approve similar** remembers the call's *similarity key* for the session:
  for Bash that's the leading command word (`git status` → all `git …`
  commands), for other tools the tool name. Remembered approvals are
  **session-only** (in memory, never persisted).
- **Safety:** a chained Bash command (`&&`, `||`, `;`, `|`, …) always
  re-prompts, even if its prefix was remembered — so an approved `git` can't
  green-light `git x && rm -rf /`.

The dialog is shown via `push_screen` + an `asyncio.Future` (not
`push_screen_wait`) because the SDK invokes the permission callback from its own
task, not a Textual worker.

## Try it

- Type a message, press **Enter** — each message gets a numbered left gutter
  with a role marker (▲ cyan = you, ▼ green = agent); the reply streams below.
- Tool calls render as collapsible `🔧` cards — the title shows a one-line
  preview (the command/path/url), and expanding shows pretty-printed JSON input.
  Click the title (or focus + Enter) to collapse/expand.
- **Ctrl+C** to quit.

### Commands

- `/model` — open a **`RadioSet` picker** of the available models. You can also
  **click "model"** in the stats panel. `/model <name>` switches directly.
- The model list is **live, not hardcoded** — read from the connected session
  via `get_server_info()["models"]` (e.g. `default` = current Opus, `sonnet`,
  `haiku`). Names resolve fuzzily, so `opus` matches the model described as
  "Opus 4.8" (i.e. `default`). The choice is **saved** as the project default.
- `/tools` — open a **checklist of built-in tools** (`SelectionList`): Space
  toggles, Save applies. You can also **click "system tools"** in the stats
  panel to open it. `/tools on` / `/tools off` quick-set all / none.
  Changing the toolset **reconnects** the agent (it's fixed at connect, so a
  fresh session is needed — the in-memory conversation resets). The choice is saved.
- **Ctrl+P** opens the command palette — models and "System tools: choose… /
  enable all / disable all" appear there too.
- **Ctrl+T** (or `/stats`) toggles the right-side stats panel.

### Per-project settings

Preferences persist in **`.textualcode.json`** in the directory you launch from
(`ProjectConfig` in `config.py`):

```json
{ "model": "haiku", "tools": ["Bash", "Read", "Edit"] }
```

- **`model`** — the default agent, restored on restart.
- **`tools`** — which built-in tools load: `null` = all, `[]` = none (chat-only),
  or an explicit subset. Fewer tools = fewer schema tokens in context (the full
  set is ~31k). Legacy `"system_tools": true/false` is migrated automatically.

Missing or corrupt files fall back to defaults.

### Session isolation

The agent connects isolated from ambient filesystem config, so behavior is
predictable and the permission dialog is authoritative:

- `strict_mcp_config=True` — ignore project/global **MCP servers**.
- `setting_sources=[]` — ignore `~/.claude` & project **settings**, including
  their `permissions.allow` rules. (Without this, a global `allow: ["*"]` would
  pre-approve every tool and the dialog would never fire.) This also means
  `CLAUDE.md` isn't loaded; pass `setting_sources=["project"]` if you want it.

### Stats panel

A light take on [claudewatcher](../claudewatcher): the SDK returns `usage` +
`total_cost_usd` each turn, which `stats.py` accumulates into session totals.
The panel shows model, turns, token breakdown (input / output / cache
write+read), **cache hit rate** (read ÷ total input, color-coded vs the ≥80 %
target), and cumulative cost. No log-watching needed.

It also includes a **light `/context` view** — the live context-window fill
(`get_context_usage()`, the same data behind Claude Code's `/context`): a
percentage + bar (color-coded, low = good) and per-category token counts
(system prompt / tools / messages). Stats = spend over time; context = how full
the window is right now.

## Background tasks panel

Below the stats panel, a **`TaskPanel`** shows live cards for background tasks
(the `Task` tool, workflows, etc.). It's driven by a **single long-lived message
pump** (`message_pump` in `app.py`) reading `client.receive_messages()` — so
progress is shown even between conversation turns. Each card (an ASCII avatar +
spinner) updates from the SDK's streamed `Task*` messages:

- `TaskStartedMessage` → create card · `TaskProgressMessage` → live
  `total_tokens` / `tool_uses` / elapsed seconds · `TaskNotificationMessage` →
  mark completed/failed/stopped + summary.

This is **free** (just consuming messages the SDK already sends). Architecture
note: the pump owns *all* incoming messages; `send_to_agent` only `submit()`s
the prompt and the pump renders the response + updates stats on `ResultMessage`.

Cards are keyed by `task_id:description`. A **workflow** shares one `task_id`
but varies the `description` per sub-agent (the agent's label), so you get one
card per sub-agent; a **real task** has a unique `task_id` + stable description →
one card. A single `TaskNotificationMessage` ends the whole task, so
`finish_task()` marks **every** card under that `task_id` complete.
`progress`/`finish` lazily create a card if their event arrives before `start`
(out-of-order safety). Set `TEXTUALCODE_DEBUG_TASKS=1` to append every `Task*`
message's ids + `usage` to `task-debug.log`.

## Notes

- **Settings** live in `textualcode/config.py` (`Settings` dataclass +
  `SYSTEM_PROMPT`): `summary_lines` (head/tail kept in the output summary),
  `max_tool_input_chars`, and `tool_preview_keys`.
- The agent loop, tools, and permissions all come from the Agent SDK;
  `textualcode/` is just the Textual UI layer around it.
