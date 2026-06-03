"""Git detection + working-tree diff helpers.

Plain functions with no Textual dependency, safe to call from a worker thread.
They shell out to ``git`` and **degrade gracefully**:

- ``NO_GIT``  — no ``git`` executable on PATH (some users simply don't have it).
- ``NO_REPO`` — ``git`` is present but ``cwd`` is not inside a work tree.
- ``OK``      — a diff (and untracked-file list) was collected.

Nothing here raises on the normal failure paths; the panel can render a
friendly placeholder for every state.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# A diff on a huge tree should never hang the UI forever; cap the subprocess.
_TIMEOUT = 15

# Caps for previewing untracked file content (read off the UI thread).
_PREVIEW_MAX_BYTES = 64 * 1024
_PREVIEW_MAX_LINES = 200

# Minimal extension -> Pygments lexer map for untracked-content previews.
# Anything unknown falls back to "text"; the panel also guards rendering.
_EXT_LEXER = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx", ".json": "json",
    ".md": "markdown", ".rst": "rst", ".css": "css", ".tcss": "css",
    ".html": "html", ".xml": "xml", ".sh": "bash", ".bash": "bash",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".cfg": "ini", ".rs": "rust", ".go": "go", ".java": "java", ".kt": "kotlin",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".sql": "sql", ".txt": "text",
}


class GitState(Enum):
    NO_GIT = "no-git"
    NO_REPO = "no-repo"
    OK = "ok"


@dataclass(frozen=True)
class FileDiff:
    """One file's worth of change, parsed out of the raw diff.

    For tracked files ``body`` is that file's unified-diff section (``lexer``
    is ``"diff"``). For untracked files ``body`` is a content preview and
    ``lexer`` is guessed from the extension.
    """

    path: str
    body: str
    added: int = 0
    removed: int = 0
    status: str = "modified"  # modified|new|deleted|renamed|binary|untracked
    is_untracked: bool = False
    lexer: str = "diff"
    old_path: str = ""  # rename source (the "from" side); "" when not a rename


@dataclass(frozen=True)
class WorkspaceDiff:
    """Result of :func:`workspace_diff` — a snapshot of uncommitted changes."""

    state: GitState
    diff: str = ""
    untracked: tuple[str, ...] = ()
    error: str | None = None
    files: tuple[FileDiff, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommitResult:
    """Outcome of :func:`commit_all`."""

    ok: bool
    message: str = ""            # the commit message that was used
    error: str | None = None
    nothing_to_commit: bool = False
    state: GitState = GitState.OK
    sha: str = ""                # short SHA of the new commit (for an undo hint)


def git_available() -> bool:
    """True if a ``git`` executable is discoverable on PATH."""
    return shutil.which("git") is not None


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT,
    )


def is_repo(cwd: Path) -> bool:
    """True only if git is installed *and* ``cwd`` is inside a git work tree."""
    if not git_available():
        return False
    try:
        result = _run(["rev-parse", "--is-inside-work-tree"], cwd)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _guess_lexer(name: str) -> str:
    return _EXT_LEXER.get(Path(name).suffix.lower(), "text")


def _parse_section(section: str) -> FileDiff:
    """Turn one ``diff --git`` section into a :class:`FileDiff`."""
    lines = section.splitlines()
    header = lines[0] if lines else ""
    status = "modified"
    old_path: str | None = None
    new_path: str | None = None
    added = removed = 0

    for ln in lines:
        if ln.startswith("new file"):
            status = "new"
        elif ln.startswith("deleted file"):
            status = "deleted"
        # Test the specific "rename from "/"rename to " prefixes BEFORE a generic
        # "rename " check would: since "rename from …" also starts with "rename ",
        # a bare `startswith("rename ")` branch ahead of these would shadow them
        # and leave old_path/new_path unset (the rename source would be lost).
        elif ln.startswith("rename from "):
            status = "renamed"
            old_path = ln[len("rename from "):]
        elif ln.startswith("rename to "):
            status = "renamed"
            new_path = ln[len("rename to "):]
        elif ln.startswith("Binary files"):
            status = "binary"
        elif ln.startswith("+++ b/"):
            new_path = ln[len("+++ b/"):]
        elif ln.startswith("--- a/") and old_path is None:
            old_path = ln[len("--- a/"):]
        elif ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1

    path = ""
    for candidate in (new_path, old_path):
        if candidate and candidate != "/dev/null":
            path = candidate
            break
    if not path:
        # Non-greedy first group so we split on the FIRST " b/", not the last;
        # the greedy form mis-parses a path that itself contains " b/". Still
        # imperfect for quoted paths with spaces — those are a rare edge case.
        match = re.match(r"diff --git a/(.*?) b/(.*)", header)
        if match:
            path = match.group(2)

    # Only surface a distinct rename source; for non-renames old_path mirrors
    # the path and would just be a redundant pathspec at commit time.
    rename_src = old_path if status == "renamed" and old_path not in ("", path) else ""

    return FileDiff(
        path=path or "(unknown)",
        body=section.rstrip("\n"),
        added=added,
        removed=removed,
        status=status,
        old_path=rename_src,
    )


def _split_diff(diff_text: str) -> list[FileDiff]:
    """Split raw ``git diff`` output into one :class:`FileDiff` per file."""
    if not diff_text.strip():
        return []
    sections: list[list[str]] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    return [_parse_section("".join(s)) for s in sections if "".join(s).strip()]


def _untracked_preview(cwd: Path, rel: str) -> FileDiff:
    """Read a size/binary-safe content preview for an untracked path."""
    target = cwd / rel
    try:
        if target.is_dir():
            return FileDiff(rel, "(untracked directory)", status="untracked",
                            is_untracked=True, lexer="text")
        raw = target.read_bytes()[:_PREVIEW_MAX_BYTES]
    except OSError:
        return FileDiff(rel, "(could not read file)", status="untracked",
                        is_untracked=True, lexer="text")

    if b"\x00" in raw:
        return FileDiff(rel, "(binary file)", status="binary",
                        is_untracked=True, lexer="text")

    text = raw.decode("utf-8", "replace")
    all_lines = text.splitlines()
    total = len(all_lines)
    shown = all_lines[:_PREVIEW_MAX_LINES]
    if total > _PREVIEW_MAX_LINES:
        shown.append(f"… ({total - _PREVIEW_MAX_LINES} more lines)")
    return FileDiff(
        path=rel,
        body="\n".join(shown),
        added=total,
        status="untracked",
        is_untracked=True,
        lexer=_guess_lexer(rel),
    )


def workspace_diff(cwd: Path) -> WorkspaceDiff:
    """Collect uncommitted changes for ``cwd``.

    Blocking (shells out to ``git``) — call off the UI thread. Returns
    ``NO_GIT`` when git is absent, ``NO_REPO`` when ``cwd`` is not a work tree,
    otherwise ``OK`` carrying ``git diff HEAD`` (staged + unstaged tracked
    changes) and the list of untracked files. On a brand-new repo with no
    commits yet, falls back to ``git diff`` since ``HEAD`` does not resolve.
    """
    if not git_available():
        return WorkspaceDiff(GitState.NO_GIT)
    try:
        inside = _run(["rev-parse", "--is-inside-work-tree"], cwd)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return WorkspaceDiff(GitState.NO_REPO)

        # `git diff HEAD` needs a HEAD; a freshly-init'd repo has none.
        has_head = _run(["rev-parse", "--verify", "--quiet", "HEAD"], cwd).returncode == 0
        diff = _run(["diff", "HEAD"] if has_head else ["diff"], cwd)

        status = _run(["status", "--porcelain"], cwd)
        untracked = tuple(
            line[3:] for line in status.stdout.splitlines() if line.startswith("??")
        )

        error = None if diff.returncode == 0 else (diff.stderr or "git diff failed").strip()

        # Group the change into one record per file (read untracked previews
        # here, on the worker thread — never on the UI loop).
        files = _split_diff(diff.stdout)
        files.extend(_untracked_preview(cwd, path) for path in untracked)

        return WorkspaceDiff(
            GitState.OK,
            diff=diff.stdout,
            untracked=untracked,
            error=error,
            files=tuple(files),
        )
    except FileNotFoundError:
        # git vanished between the PATH check and the call.
        return WorkspaceDiff(GitState.NO_GIT)
    except (OSError, subprocess.SubprocessError) as exc:
        return WorkspaceDiff(GitState.OK, error=str(exc))


def render_diff_text(result: WorkspaceDiff) -> str:
    """Flatten a :class:`WorkspaceDiff` into one text blob for a model to read.

    Combines the tracked unified diff (``git diff HEAD``) with a labelled
    content preview for each untracked file, so a review/commit model sees the
    whole working-tree change in a single payload. Returns ``""`` when there is
    nothing uncommitted.
    """
    parts: list[str] = []
    if result.diff.strip():
        parts.append(result.diff.rstrip())
    for f in result.files:
        if f.is_untracked and f.body.strip():
            parts.append(f"# Untracked file: {f.path}\n{f.body.rstrip()}")
    return "\n\n".join(parts).strip()


def staged_pathspecs(result: WorkspaceDiff) -> list[str]:
    """The pathspecs to stage for a commit: exactly the files in the reviewed
    snapshot (tracked changes + untracked previews), plus the rename source so a
    detected rename stages as a rename rather than an add.

    Scoping ``git add`` to these — instead of a blanket ``git add -A`` — keeps
    files that appeared *after* the snapshot, or that live outside the diff
    entirely, out of the commit, so the committed content matches what was
    reviewed and the drafted message describes.
    """
    seen: dict[str, None] = {}  # dict preserves insertion order while de-duping
    for f in result.files:
        for p in (f.path, f.old_path):
            if p and p != "(unknown)" and p not in seen:
                seen[p] = None
    return list(seen)


def commit_all(cwd: Path, message: str, paths: list[str] | None = None) -> CommitResult:
    """Stage the given ``paths`` (or everything if ``None``) and commit.

    ``paths`` should be the reviewed snapshot's pathspecs (see
    :func:`staged_pathspecs`); they are staged with ``git add -A -- <paths>`` so
    only the reviewed changes are committed — never unrelated or post-snapshot
    files a blanket ``git add -A`` would sweep in. (Content is staged as it is at
    commit time, so a reviewed file edited in the interim commits its current
    state; only the *set* of files is bounded.)

    Blocking (shells out to ``git``) — call off the UI thread. Degrades
    gracefully: returns a ``CommitResult`` flagging ``NO_GIT`` / ``NO_REPO``,
    an empty tree (``nothing_to_commit``), or any git error, and never raises
    on the normal failure paths.
    """
    if not git_available():
        return CommitResult(False, message, error="git is not installed",
                            state=GitState.NO_GIT)
    try:
        inside = _run(["rev-parse", "--is-inside-work-tree"], cwd)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return CommitResult(False, message, error="not a git repository",
                                state=GitState.NO_REPO)

        add_args = ["add", "-A", "--", *paths] if paths else ["add", "-A"]
        add = _run(add_args, cwd)
        if add.returncode != 0:
            return CommitResult(False, message,
                                error=(add.stderr or "git add failed").strip())

        commit = _run(["commit", "-m", message], cwd)
        if commit.returncode != 0:
            combined = f"{commit.stdout}\n{commit.stderr}".lower()
            if "nothing to commit" in combined:
                return CommitResult(False, message, nothing_to_commit=True)
            return CommitResult(
                False, message,
                error=(commit.stderr or commit.stdout or "git commit failed").strip(),
            )
        # Best-effort short SHA for the success note / undo hint; never fatal.
        rev = _run(["rev-parse", "--short", "HEAD"], cwd)
        sha = rev.stdout.strip() if rev.returncode == 0 else ""
        return CommitResult(True, message, sha=sha)
    except FileNotFoundError:
        return CommitResult(False, message, error="git is not installed",
                            state=GitState.NO_GIT)
    except (OSError, subprocess.SubprocessError) as exc:
        return CommitResult(False, message, error=str(exc))
