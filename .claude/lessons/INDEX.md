# Lessons Index

Cross-session lessons harvested from coding sessions. Each line is an imperative rule; open the file for detail.

## Refactoring

- [test-links-after-tool-rename.md](test-links-after-tool-rename.md) — After renaming tools or modules, verify all navigation links and handler references function end-to-end before declaring the refactor complete, to prevent broken routing and stuck state.

## UX Safety

- [guard-signal-handlers-with-confirmation.md](guard-signal-handlers-with-confirmation.md) — Add confirmation prompts before acting on terminal signals (Ctrl+C, SIGINT) when the signal could interrupt valuable work in progress to prevent accidental user errors.

## Textual

- [avoid-textual-underscore-collisions.md](avoid-textual-underscore-collisions.md) — Never name instance attributes with single underscores matching parent class internals (_running on MessagePump, _render on Widget); use descriptive compound names like _turn_active to prevent silent attribute shadowing that breaks behavior without raising errors.
- [textual-prevent-default-not-stop-for-private-handlers.md](textual-prevent-default-not-stop-for-private-handlers.md) — When overriding a private `_on_*` handler (e.g. `_on_paste`), call `event.prevent_default()` to suppress the base-class behavior; `event.stop()` only halts bubbling and Textual still runs the inherited handler via MRO dispatch, causing duplicate actions (e.g. pasted text inserted twice).
- [prevent-default-vs-stop-for-mro-handlers.md](prevent-default-vs-stop-for-mro-handlers.md) — In Textual event handlers overriding _on_*, call event.prevent_default() to suppress inherited base-class handlers in the MRO chain; event.stop() only stops bubbling to parents and does not prevent sibling base-class handlers from executing.

## UX

- [long-tasks-need-progress-animation.md](long-tasks-need-progress-animation.md) — Display live animated progress (spinner + elapsed seconds) for any async task exceeding 5 seconds, or users perceive the UI as completely hung even when the backend is working correctly.
- [two-step-quit-with-confirm-window.md](two-step-quit-with-confirm-window.md) — Implement destructive actions (quit, delete, reset) as two-step confirms with ~3 second timeout: first action arms and shows 'Press again to confirm' inline; second press within window executes; timeout disarms silently.
- [confirm-termination-signals.md](confirm-termination-signals.md) — Always add confirmation before executing destructive keyboard signals (ctrl+c, etc.) to prevent accidental operation termination.
- [dialog-after-long-operations.md](dialog-after-long-operations.md) — Display a completion dialog after long-running operations to confirm success state and present next-step options.
- [confirm-signal-interruption.md](confirm-signal-interruption.md) — Add confirmation dialogs for keyboard interrupt signals (Ctrl+C) to prevent accidental termination of long-running operations.

## Workflow

- [verify-api-not-guess.md](verify-api-not-guess.md) — Never guess an API or framework behavior—always verify against authoritative sources (web search, GitHub, upstream source, official docs) before implementing; cite your sources.
- [consult-installed-source-for-data-structures.md](consult-installed-source-for-data-structures.md) — When investigating a framework's data structures or API surface, consult the installed source code and docs instead of memory — this is how you discover available fields (e.g., model_usage with costUSD) and avoid false 'not available' conclusions.
- [verify-api-web-search-first.md](verify-api-web-search-first.md) — Check the installed API version first, then search Anthropic's official docs (or library GitHub) scoped to that version instead of reading .venv source immediately, preventing stale or incorrect API calls due to outdated version assumptions.
- [verify-undocumented-apis-against-source.md](verify-undocumented-apis-against-source.md) — When relying on undocumented internal APIs, verify behavior against the installed source code directly rather than public documentation, to prevent depending on unstable implementation details.

## SDK Configuration

- [session-config-cascades-with-exceptions.md](session-config-cascades-with-exceptions.md) — Session or context-level config (setting_sources, system_prompt, etc.) cascades to spawned subcomponents — set once at the session level and check the docs for subcomponent-specific exceptions.
- [document-config-side-effects.md](document-config-side-effects.md) — When enabling new config sources (filesystem settings, permissions, etc.), verify and document all side effects that change behavior beyond the intended feature (e.g., auto-approval of tools via permissions.allow rules).

## Cost Tracking

- [model-id-format-mismatch-in-cost-tracking.md](model-id-format-mismatch-in-cost-tracking.md) — When comparing model IDs from different SDK sources, verify they use identical formatting; AssistantMessage.model lacks tier suffixes that model_usage keys carry (e.g., [1m]), so strip suffixes before comparing or cost will systematically misattribute to the wrong bucket.
- [task-tokens-not-model-for-subagent-split.md](task-tokens-not-model-for-subagent-split.md) — Discriminate main agent from subagent cost using Task-message token counts and parent_tool_use_id, not model ID, because a subagent can run the same model as the main agent and model_usage keys keyed by model alone cannot separate them.
- [preserve-within-model-cost-granularity.md](preserve-within-model-cost-granularity.md) — When splitting cost across agents that may share a model, preserve per-model cost from model_usage and split only within a single model by token proportion, because per-token rates differ across models.

## SDK Integration

- [no-first-class-per-subagent-cost-api.md](no-first-class-per-subagent-cost-api.md) — The Claude Agent SDK does not expose per-subagent cost granularity; implement splits via Task notification tokens combined with per-model model_usage, or accept that include_partial_messages with StreamEvent parent_tool_use_id yields raw deltas without cost data.

## Debugging

- [diagnose-sdk-shapes-empirically.md](diagnose-sdk-shapes-empirically.md) — When SDK data shapes or formats are uncertain, run diagnostics against the live SDK with actual app connect options before designing; format mismatches (model ID suffixes, field presence, token accounting) only surface in practice, not in docs.

## UI

- [no-confirmation-non-destructive-action.md](no-confirmation-non-destructive-action.md) — Execute non-destructive actions (interrupt, pause, cancel) immediately without confirmation to match user expectations, preventing unnecessary friction and delays for reversible operations.
- [group-streaming-items-collapsibly.md](group-streaming-items-collapsibly.md) — Group consecutive streaming operations (tool calls, function invocations) into a single collapsible container with a summary header, expanding on demand, to prevent UI clutter and keep conversations scannable.

## Architecture

- [flag-interruptible-operation-precisely.md](flag-interruptible-operation-precisely.md) — Flag the specific interruptible operation (not just the UI state) when multiple concurrent operations share a loading indicator, preventing interrupt signals from accidentally affecting unrelated work.
- [reset-groups-at-turn-boundaries.md](reset-groups-at-turn-boundaries.md) — When grouping sequential operations in a conversation UI, reset the grouping at turn boundaries (agent text, user questions, result messages) to preserve conversational flow and logic.
