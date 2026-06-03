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
#    Get-Command reads the real Windows PATH, but a freshly-installed tool may
#    not be on this session's PATH yet, so also probe well-known locations.
function Test-Dep($name, $paths) {
  if (Get-Command $name -ErrorAction SilentlyContinue) { return $true }
  foreach ($p in $paths) { if ($p -and (Test-Path $p)) { return $true } }
  return $false
}

$missing = @()
if (-not (Test-Dep "claude" @(
    "$env:USERPROFILE\.local\bin\claude.exe",
    "$env:USERPROFILE\.local\bin\claude",
    "$env:APPDATA\npm\claude.cmd"))) { $missing += "claude" }
if (-not (Test-Dep "node" @(
    "$env:ProgramFiles\nodejs\node.exe",
    "${env:ProgramFiles(x86)}\nodejs\node.exe",
    "$env:LOCALAPPDATA\Volta\bin\node.exe"))) { $missing += "node" }

Write-Host ""
Info "tcode installed."
if ($missing.Count -gt 0) {
  Warn "   Note: couldn't confirm in this session: $($missing -join ', ')"
  Warn "   tcode needs Node 18+ and the claude CLI at runtime. Verify with:"
  Warn "       node --version  ;  claude --version"
  Warn "   If genuinely missing: install Node 18+; npm i -g @anthropic-ai/claude-code"
}
Info "   Open a NEW terminal, cd into any project, and run:  tcode"
