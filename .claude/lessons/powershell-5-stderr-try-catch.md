# powershell-5-stderr-try-catch

In PowerShell 5.1 scripts with $ErrorActionPreference = 'Stop', native command stderr cannot be suppressed by output redirects alone (*> $null); wrap in try { ... } catch { } instead, to prevent informational stderr from becoming terminating errors in user-facing installers.

_Category: PowerShell_
