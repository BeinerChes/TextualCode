# auto-mode-persists-to-usersettings-only

Persist Claude Agent SDK auto permission mode only to ~/.claude/settings.json (userSettings), never to .claude/settings.json (projectSettings) or .claude/settings.local.json (localSettings), because the CLI silently ignores defaultMode: auto in project and local scopes (2.1.142+), producing a no-op 

_Category: Permissions_
