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
# This check is best-effort. On Windows the installer runs in a git-bash
# subshell whose PATH is a stripped subset of the real Windows PATH, and any
# child process (where.exe, cmd.exe) inherits that same stripped PATH — so
# `command -v` can't see tools that tcode.exe WILL find at runtime. We can't
# read the live runtime PATH from here, so we additionally probe the well-known
# install locations directly (filesystem checks work regardless of PATH).
have() {
  command -v "$1" >/dev/null 2>&1 && return 0
  case "$1" in
    node)
      for p in \
        "/c/Program Files/nodejs/node.exe" \
        "/c/Program Files (x86)/nodejs/node.exe" \
        "${ProgramFiles:-}/nodejs/node.exe" \
        "${LOCALAPPDATA:-}/Volta/bin/node.exe"; do
        [ -n "$p" ] && [ -e "$p" ] && return 0
      done ;;
    claude)
      for p in \
        "$HOME/.local/bin/claude" \
        "$HOME/.local/bin/claude.exe" \
        "${APPDATA:-}/npm/claude" \
        "${APPDATA:-}/npm/claude.cmd" \
        "$HOME/node_modules/.bin/claude"; do
        [ -n "$p" ] && [ -e "$p" ] && return 0
      done ;;
  esac
  return 1
}

MISSING=""
have claude || MISSING="$MISSING claude"
have node   || MISSING="$MISSING node"

echo
info "✅ tcode installed."
if [ -n "$MISSING" ]; then
  warn "   Note: couldn't confirm from this installer shell:$MISSING"
  warn "   (curl|bash runs in a subshell that may not see your full PATH —"
  warn "    this is often a false alarm.) tcode needs Node 18+ and the claude"
  warn "    CLI at runtime; verify in your normal terminal:"
  warn "        node --version   &&   claude --version"
  warn "    If genuinely missing: install Node 18+; npm i -g @anthropic-ai/claude-code"
fi
info "   Open a new terminal, cd into any project, and run:  tcode"
