#!/usr/bin/env sh
# TextualCode installer — installs the `tcode` command.
#
#   curl -fsSL https://raw.githubusercontent.com/BeinerChes/TextualCode/main/install.sh | bash
#
# Override the source repo/ref with env vars, e.g.:
#   TCODE_REPO=youruser/yourfork TCODE_REF=v0.1.0 ./install.sh
set -eu

OWNER_REPO="${TCODE_REPO:-BeinerChes/TextualCode}"
REF="${TCODE_REF:-main}"
PKG="git+https://github.com/${OWNER_REPO}.git@${REF}"

info() { printf '\033[36m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# 1. Ensure uv (Python tool manager). It also fetches a compatible Python.
if ! command -v uv >/dev/null 2>&1; then
  info "uv not found — installing it..."
  curl -fsSL https://astral.sh/uv/install.sh | sh || die "Failed to install uv."
  # The uv installer drops binaries here; put them on PATH for this session.
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH; open a new shell and re-run."

# 2. Install (or upgrade) the tcode command from GitHub.
#    --force makes re-runs idempotent (acts as an upgrade).
info "Installing tcode from ${OWNER_REPO}@${REF} ..."
uv tool install --force "$PKG" || die "Install failed."

# 3. Make sure uv's tool bin dir is on PATH in future shells.
uv tool update-shell >/dev/null 2>&1 || true

# 4. Runtime prerequisites (the Claude Agent SDK shells out to these).
#
# Resolve commands the way tcode will at runtime. On Windows this installer
# usually runs in a git-bash subshell with a reduced PATH, but tcode.exe is a
# native process that inherits the *Windows* PATH — so a plain `command -v`
# here gives false "not found" warnings. Also ask Windows' own resolver
# (cmd.exe `where`) when available, which reflects the PATH tcode actually sees.
have() {
  command -v "$1" >/dev/null 2>&1 && return 0
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c "where $1" >/dev/null 2>&1 && return 0
  fi
  return 1
}

MISSING=0
if ! have claude; then
  warn "⚠  'claude' CLI not found. tcode needs it at runtime:"
  warn "     npm install -g @anthropic-ai/claude-code"
  MISSING=1
fi
if ! have node; then
  warn "⚠  Node.js not found (required by the Claude Agent SDK). Install Node 18+."
  MISSING=1
fi

echo
info "✅ tcode installed."
[ "$MISSING" -eq 0 ] || warn "   Resolve the warnings above before first run."
info "   Open a new terminal, cd into any project, and run:  tcode"
