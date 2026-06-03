# TextualCode

A Claude-Code-style terminal UI built with [Textual](https://textual.textualize.io/),
driving the official [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk).
Header, scrollable conversation, and an input box — assistant text and tool calls
stream into the UI live. Installs a `tcode` command you can run from any folder,
as an alternative front-end to the `claude` CLI.

## Prerequisites

TextualCode is a UI *around* the Agent SDK, which shells out to the Claude Code
CLI — so you need both of these on your PATH at runtime:

- **Node.js 18+** — required by the Agent SDK.
- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code` (or the native
  installer). Log in once with `claude` → `/login`.

The installer also needs [uv](https://docs.astral.sh/uv/); if it's missing it
will bootstrap it for you (and fetch a compatible Python).

## Install

Pick the line for your shell:

**PowerShell**
```powershell
irm https://raw.githubusercontent.com/BeinerChes/TextualCode/main/install.ps1 | iex
```

**cmd / Git Bash / macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/BeinerChes/TextualCode/main/install.sh | bash
```

> In PowerShell, `curl` is an alias for `Invoke-WebRequest` and won't accept
> `-fsSL` — use the `irm … | iex` line instead.

The installer drops a `tcode` launcher on your PATH (via `uv tool install`) and
installs all dependencies into an isolated environment. Open a **new** terminal
afterwards so the PATH change takes effect.

### Pin a version

Both installers honor `TCODE_REF` (a tag, branch, or commit) and `TCODE_REPO`
(an `owner/repo` fork):

```powershell
$env:TCODE_REF = "v0.1.0"; irm https://raw.githubusercontent.com/BeinerChes/TextualCode/main/install.ps1 | iex
```
```bash
TCODE_REF=v0.1.0 bash -c "$(curl -fsSL https://raw.githubusercontent.com/BeinerChes/TextualCode/main/install.sh)"
```

## Run

From any project folder:

```
tcode
```

It uses the current directory as the project root (reads that folder's
`CLAUDE.md` / `.claude`, etc.) — the same model as the `claude` command.

### Auth

It uses whatever the **Claude Code CLI** is logged in with — your Pro/Max
subscription or an `ANTHROPIC_API_KEY`. 

## Update / uninstall

```
uv tool upgrade textualcode      # re-pull latest from the installed source
uv tool uninstall textualcode    # remove tcode and its environment
```

To force a fresh reinstall from GitHub, just re-run the install one-liner.

## Run from source (development)

```powershell
# from the TextualCode folder
uv sync                      # create .venv and install deps
uv run python -m textualcode # launch the app
```

To make `tcode` always reflect your working tree instead of a built copy:

```
uv tool install --editable .
```
