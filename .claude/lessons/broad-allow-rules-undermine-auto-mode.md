# broad-allow-rules-undermine-auto-mode

Clean up overly broad allow rules (Bash(*), PowerShell(*), Agent wildcards) before relying on auto permission mode's classifier, because entering auto mode drops broad rules temporarily but users may not expect classifier overhead for pre-approved commands; keep allow rules narrowly scoped.

_Category: Permissions_
