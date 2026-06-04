# Session State — 2026-06-04

## Goal
Add an 'Auto' button to the tool-approval permission dialog in a TCode app (Anthropic Claude Agent SDK) that enables auto-mode permission classification and optionally saves the mode to user settings

## Why
User was testing the Pretty tool's JSON rendering and discovered the global permission allowlist has blanket rules (`"*"` and `Bash(*)`). After removing the blanket rule to see permission dialogs, they realized a gap: a way to upgrade from manual per-call approval to an auto-classifier mode without permanently disabling dialogs, while keeping the ability to control it per session

## What was done
- Ran test bash commands (echo, date, uname, curl, env) to observe tool output rendering and permission system behavior
- Read .claude/settings.json and ~/.claude/settings.json to discover blanket `"*"` and `Bash(*)` allow rules
- Removed the blanket `"*"` allow rule from global settings via Edit tool
- Confirmed permission dialog appeared for subsequent tool calls after removal
- Researched Claude Code permission modes via WebSearch and WebFetch against official Anthropic docs
- Read installed SDK source (claude-agent-sdk v0.2.88) to understand PermissionMode, PermissionResult, PermissionUpdate types and set_permission_mode() control flow
- Verified bundled CLI version (2.1.161) meets auto-mode requirements (2.1.83+)
- Traced SDK control protocol to confirm set_permission_mode() returns success/error only, not active mode confirmation
- Discovered auto-mode persists only to ~/.claude/settings.json, not localSettings (CLI 2.1.142+ ignores auto from project/local scopes)
- Identified model-capability gate as robust alternative to live detection (auto requires Opus 4.6+/Sonnet 4.6)
- Read full TCode app codebase: permissions.py, screens.py, agent.py, app.py, config.py, app.tcss
- Added `auto` bool flag to Decision type in permissions.py
- Implemented model_supports_auto() heuristic in config.py with _resolve_model_text() helper to classify model versions
- Added 'Auto (u)' button to PermissionDialog in screens.py with keybinding and action handler
- Implemented _activate_auto_mode() method in agent.py to call set_permission_mode() with fallback to acceptEdits for unsupported models
- Implemented _write_user_default_mode() method with merge-preserving JSON read/update/write to ~/.claude/settings.json
- Added notifier callback to agent.py to communicate mode-change feedback to user via TUI
- Wired notifier into AgentSession construction in app.py
- Updated app.tcss button sizing to fit 4 buttons in 72-wide dialog without horizontal overflow
- Ran Python syntax and import check on all modified files
- Tested settings merge logic with temporary file copies to verify preservation of existing keys
- Ran full test suite (299 tests) to verify no regressions
- Performed headless dialog render and button interaction test via Textual pilot to confirm button + keybinding

## Mistakes / corrections
- Initially tried various bash commands to trigger permission dialog, not realizing blanket `"*"` allow rule was suppressing all prompts
- First considered persisting auto mode to localSettings, only discovering later that CLI 2.1.142+ ignores auto there (must use userSettings)
- Attempted to implement live detection via get_server_info() and control-response inspection, but traced SDK code and found no active mode readback available
- Initially planned to rely on undocumented SDK methods to detect active mode, but per project rules switched to model-gate heuristic instead

## Result
Implemented a 4th 'Auto (u)' button in the tool-approval dialog. On click: (1) persists permissions.defaultMode='auto' to ~/.claude/settings.json (merge-preserving existing keys); (2) live-switches session via set_permission_mode('auto') if model supports it (Opus 4.6+/Sonnet 4.6), otherwise falls back to 'acceptEdits' with user notification; (3) notifies user which mode actually engaged. All 299 existing tests pass; headless dialog test confirms button renders, keybinding returns Decision(auto=True), and settings merge preserves unrelated config keys. One step pending: real terminal launch to visually verify 4-button layout and observe actual auto-mode engagement against live SDK.  _(satisfied: partial)_

## Next
- Launch TCode app in real terminal to visually confirm 4-button layout fits without overflow or truncation
- Trigger actual auto-mode switch against live SDK with Opus 4.6/Sonnet 4.6 model to confirm classifier behavior
- Test fallback path: attempt auto with a model version below 4.6 (e.g., Sonnet 4.5) to verify acceptEdits fallback + notification
- Verify ~/.claude/settings.json persists auto mode across app restarts and new session launches

## Map
- **keywords:** claude-agent-sdk, permissions, auto-mode, bypassPermissions, dangerously-skip-permissions, PermissionMode, PermissionResult, PermissionUpdate, CanUseTool, set_permission_mode, model-gate, settings.json, userSettings, localSettings, projectSettings, Dialog, CLI, SDK, Textual, TCode, 0.2.88, 2.1.161, Opus 4.6, Sonnet 4.6, acceptEdits, dontAsk, plan, merge-preserving, headless-test, notifier, keybinding
- **keyfiles:** ~/.claude/settings.json, permissions.py, config.py, screens.py, agent.py, app.py, app.tcss
