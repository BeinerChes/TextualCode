# Refactoring Plan — `textualcode/app.py` (`TextualCodeApp`)

> Generated from a multi-agent audit (5 analysis lenses + adversarial verification).
> 47 findings: **3 confirmed bugs**, 3 rejected (false positives), 11 smells,
> 17 responsibilities, 13 best-practice gaps. Best-practice findings were
> web-verified against Textual ≥0.80 and claude-agent-sdk ≥0.2.88 docs.

## 1. Diagnosis: why this is a god class

`TextualCodeApp` is a 606-line `App` whose docstring claims it is "wiring only,"
but the responsibility map (R01–R17) shows it actually owns **sixteen distinct
concerns** plus all of their state. It is the sole owner of the agent connection
state machine (R02: `connect_agent`/`reconnect_agent`/`restart_session`), the SDK
message pump and dispatch table (R03: `message_pump`/`_dispatch`/`_task_key`),
per-turn cost reconciliation (R04: `_on_turn_complete` reaching into
`_renderer.last_usage/last_cost/last_model_usage/main_models` plus
`_turn_subagent_tokens`), the SDK-callback↔Textual modal bridge (R06:
`_ask_permission`/`_ask_question`), the full model feature (R07), the full tools
feature (R08), the two-step quit machine (R09), the interrupt machine (R10),
harvest orchestration (R11: the 54-line `harvest_now`), command registration
(R12), prompt-input control (R13), debug logging (R14), palette population (R15),
and stats-panel refresh (R16). Because every one of these stores its state as a
bare instance attribute in one `__init__` (R17), the class is a single coupling
point where 16 features' fields sit side-by-side — the structural signature of a
god class. The duplication confirms it: one error-reporting shape copied into
8 `except` blocks (`smell-01`), `sub_title` written in 8+ places with no owner
(`smell-02`), `_stats_panel.show(...)` called from 4 sites with a divergent model
arg (`smell-03`). The `_agent_turn_active` flag is mutated in **three** methods,
which is exactly the smear that causes confirmed bug #1.

---

## 2. Target architecture

**Principle (verified, `bp-04`):** Textual's guidance is to keep the `App` as
composition/wiring and push non-UI behaviour into separate controller/data
objects. The `App` keeps only: `compose()`, the `query_one` handle-binding in
`on_mount`, the `action_*` entry points, the Textual message handlers
(one-liners), and references to controllers. `@work` workers and
`push_screen_wait` must stay on the App (they need a `MessagePump`), but become
thin shims that `await controller.method()`.

### New module / class list

| File | Class | Owns |
|---|---|---|
| `status.py` | `StatusPresenter` | The single owner of `sub_title`. `set_phase(...)` recomputes from state. Fixes `smell-02`/`bug-sub-title-race`. |
| `status.py` | `StatsView` | Holds `(stats, model_label, last_context)`; one `render()`. Collapses 4 divergent `show()` sites (`smell-03`, R16). |
| `session_controller.py` | `SessionController` | connect/reconnect/restart state machine + explicit pump teardown/rebind + **single source of truth for `turn_active`**. Folds R02, R03 (pump lifecycle), R10. |
| `dispatcher.py` | `MessageDispatcher` | `_dispatch` type-switch + `_task_key` + Task-token accrual. Folds R03 routing, `smell-06`/`smell-07`. |
| `dispatcher.py` | `TaskDebugLog` | Env-gated (`TEXTUALCODE_DEBUG_TASKS`) file logger; `record(message)`. Removes file-I/O from App (R14). |
| `accounting.py` | `TurnAccountant` | `UsageStats` + `turn_subagent_tokens`; `begin_turn()`, `accrue_subagent_tokens(usage)`, `commit_turn(result)`. Co-locates reset+consume (fixes bug #2). Folds R04. |
| `modal_bridge.py` | `ModalBridge` | `push_screen`+`Future` for `ask_permission`/`ask_question`; similarity-label derivation; tracks pending future for deny-on-interrupt (`sdk-05`). Folds R06. |
| `model_controller.py` | `ModelController` | `_models` cache, `apply(value)`, `pick_via_selector()`, `entries()` palette generator. Folds R07, R15(model). |
| `tools_controller.py` | `ToolsController` | `apply(tools)` (persist + reconnect via `SessionController`), `parse_command(arg)`, selector w/ all→`None`, `entries()`. Folds R08, R15(tools). |
| `harvest_controller.py` | `HarvestController` | `run()` → `Harvester.run` → `write_harvest` → summary → `ConfirmDialog` → restart via `SessionController`. Folds R11. |
| `quit_guard.py` | `QuitGuard` | Armed flag + timer + `_QUIT_WINDOW`; `request(on_confirm)`; notice/toast. Folds R09. |
| `errors.py` | `report_error` / `@reporting` | Single async error-report helper collapsing the 8 `except` blocks. Fixes `smell-01`. |
| `groups.py` | `Groups` | Worker-group name constants. Fixes `smell-08`. |

### Slimmed `TextualCodeApp`
- `__init__`: construct config + controllers; pass `bridge.ask_permission`/`bridge.ask_question` into `AgentSession`. Retains only controller refs + 5 widget handles.
- `compose()` / `on_mount` handle-binding: **stays** (R01 — genuine App responsibility).
- `action_*`: one-liners delegating to controllers.
- Message handlers: `@on(PromptInput.Submitted)` / `@on(PromptInput.FileDropped)` (verified `bp-03`).
- `@work` shims stay on the App as thin worker bodies awaiting controller coroutines (respects `bp-05`).

---

## 3. Ordered, incremental migration sequence

Each step compiles and runs the TUI on its own. Bug fixes are folded into the step that owns the relevant code.

**Step 0 — Safety net + constants (no behaviour change).** Add `groups.py` and `errors.py`. Replace the 8 `except` bodies and 10 `@work(group=...)` literals. *Fixes `smell-01`, `smell-08`.*

**Step 1 — `StatusPresenter` + `StatsView`.** Route every `sub_title` write and `stats_panel.show(...)` through them. *Fixes `smell-02`, `smell-03`, `bug-sub-title-race`, the `switch_model` value-vs-label divergence.*

**Step 2 — `TaskDebugLog` + `MessageDispatcher`.** Extract `_task_key`/`_log_task`/`_dispatch`. Pump becomes `await dispatcher.handle(message)`. **Rename `message_pump` → `read_agent_stream`** (`bp-06`) and **narrow the bare `except Exception: pass`** to `CancelledError`/connection-closed (**fixes confirmed bug #3** — silent pump death). Tighten `_dispatch` (`smell-07`).

**Step 3 — `TurnAccountant`.** Move `_turn_subagent_tokens` + `UsageStats` + reset/accrue/commit here. **Fixes confirmed bug #2** by co-locating reset+consume and adding `if not is_turn_active: return` guard.

**Step 4 — `SessionController` (highest value).** Move connect/reconnect/restart + the `_agent_turn_active` flag here; expose `is_turn_active`/`begin_turn`/`end_turn`/`interrupt`. App methods become shims. Fold `_reconnect_and_rebind` (`smell-04`). **Fixes confirmed bug #1**: reconnect/restart call `end_turn()` (stop ThinkingBar, clear flag) before teardown. Also fold `bug-interrupt-vs-result-double-markdown` and explicit pump teardown (`sdk-03`).

**Step 5 — `ModalBridge`.** Move `_ask_permission`/`_ask_question`; pass bridge methods to `AgentSession`. Track pending future for deny-on-interrupt (`sdk-05`).

**Step 6 — `ModelController` + `ToolsController`.** Move R07/R08 + `_models`. `get_system_commands` becomes `yield from` per controller. **Fixes `bug-models-populated-after-connect-palette-stale`** (read `agent.available_models()` live).

**Step 7 — `HarvestController` + `QuitGuard`.** Move `harvest_now` orchestration and the quit machine.

**Step 8 — Command/input cleanup + `__init__` re-homing (R12/R13/R17).** Command factory, `@on` handlers, `__init__` becomes a true composition root.

*(Optional follow-up — `bp-01`/`bp-07`: promote `turn_active`/`quit_armed` to `reactive(..., init=False)` with `watch_*` hooks once ownership is consolidated.)*

---

## 4. Codebase-specific risks

- **Worker groups must keep identical string values** — Step 0 `Groups` constants preserve cancel/replace semantics byte-for-byte. Keep `@work` on the App, not controllers.
- **Pump rebinding / client torn out from under the pump (`sdk-03`)** — narrow the catch (Step 2) *before* making teardown explicit (Step 4): `cancel_group(PUMP)` → `agent.reconnect()` → fresh pump.
- **SDK-callback vs worker threading (`bp-02`, `sdk-05`)** — `ask_permission`/`ask_question` run on the SDK's own task → keep `push_screen`+`Future`, NOT `push_screen_wait`. Selectors run in workers → keep `push_screen_wait`.
- **`_agent_turn_active` single-source-of-truth** — Step 4 routes all 3 former mutation sites through `begin_turn`/`end_turn`/`interrupt`.
- **Underscore/name collisions** — renaming `message_pump` avoids the Textual "message pump" concept; no single-underscore attrs matching `MessagePump`/`Widget` internals on new controllers.

---

## 5. Verification protocol (per step — mandatory)

1. `python -c "import textualcode.app"` — imports resolve.
2. **Grep for the old symbol after every rename** (`message_pump`, `_dispatch`, `_ask_permission`, `_apply_tools`, each former `register(...)` name) — zero dangling refs; every clickable `action_*`, slash command, and palette entry routes end-to-end.
3. **Run the TUI** and exercise the step's surface (connect → real prompt → streaming render → turn completes; then interrupt / reconnect via `/tools` / `/model` / `/harvest` / Ctrl+C-twice). Never declare a step done on compile alone.

### Confirmed bugs (fix during refactor)
| # | Severity | Bug | Fixed in |
|---|---|---|---|
| 1 | medium | Reconnect/restart mid-turn strands `_agent_turn_active=True`, ThinkingBar spins forever | Step 4 |
| 2 | low | `_turn_subagent_tokens` reset not co-located with consume → double-bill on stray 2nd `ResultMessage` | Step 3 |
| 3 | medium | `message_pump` swallows ALL exceptions → silent pump death hides render/dispatch bugs | Step 2 |
