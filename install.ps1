# TextualCode installer (Windows / PowerShell) — installs the `tcode` command.
#
#   irm https://raw.githubusercontent.com/BeinerChes/TextualCode/main/install.ps1 | iex
#
# Override the source repo/ref with env vars before running, e.g.:
#   $env:TCODE_REPO="youruser/yourfork"; $env:TCODE_REF="v0.1.0"
$ErrorActionPreference = "Stop"

$OwnerRepo = if ($env:TCODE_REPO) { $env:TCODE_REPO } else { "BeinerChes/TextualCode" }
$Ref       = if ($env:TCODE_REF)  { $env:TCODE_REF }  else { "main" }
$Pkg       = "git+https://github.com/$OwnerRepo.git@$Ref"

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }

# 1. Ensure uv (also fetches a compatible Python).
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Info "uv not found - installing it..."
  irm https://astral.sh/uv/install.ps1 | iex
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. Install (or upgrade) the tcode command from GitHub.
Info "Installing tcode from $OwnerRepo@$Ref ..."
uv tool install --force $Pkg
uv tool update-shell *> $null

# 3. Runtime prerequisites (the Claude Agent SDK shells out to these).
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
  Warn "WARNING: 'claude' CLI not found. tcode needs it at runtime:"
  Warn "         npm install -g @anthropic-ai/claude-code"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Warn "WARNING: Node.js not found (required by the Claude Agent SDK). Install Node 18+."
}

Write-Host ""
Info "tcode installed. Open a NEW terminal, cd into any project, and run:  tcode"
