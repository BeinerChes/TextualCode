"""Persist harvested output: an ephemeral session map + durable lessons.

`state.md` is overwritten each harvest (current session only). The lessons
`INDEX.md` and per-lesson files are append-only and deduped by slug — mirroring
a progressive-disclosure Skill: the index is a cheap router, each lesson file is
paged in only when its keywords match. Curation (placement, dedup) lives here in
Python, not in the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .harvest import HarvestResult, Lesson

LESSONS_DIRNAME = "lessons"
_INDEX_HEADER = (
    "# Lessons Index\n\n"
    "Cross-session lessons harvested from coding sessions. Each line is an "
    "imperative rule; open the file for detail.\n"
)


@dataclass
class HarvestPaths:
    root: Path
    state: Path
    index: Path
    new_lessons: list[Path]


def write_harvest(
    project_dir: Path, result: HarvestResult, *, subdir: str = ".claude"
) -> HarvestPaths:
    """Write `state.md` and merge any new lessons into the index. Returns paths."""
    root = project_dir / subdir
    lessons_dir = root / LESSONS_DIRNAME
    lessons_dir.mkdir(parents=True, exist_ok=True)

    state_path = root / "state.md"
    state_path.write_text(_render_state(result), encoding="utf-8")

    index_path = lessons_dir / "INDEX.md"
    new_paths = _write_lessons(lessons_dir, index_path, result.lessons)

    return HarvestPaths(root=root, state=state_path, index=index_path, new_lessons=new_paths)


# --------------------------------------------------------------- state.md --
def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- _(none)_"


def _render_state(r: HarvestResult) -> str:
    return (
        f"# Session State — {date.today().isoformat()}\n\n"
        f"## Goal\n{r.goal or '_(unknown)_'}\n\n"
        f"## Why\n{r.why or '_(unknown)_'}\n\n"
        f"## What was done\n{_bullets(r.did)}\n\n"
        f"## Mistakes / corrections\n{_bullets(r.mistakes)}\n\n"
        f"## Result\n{r.result or '_(unknown)_'}  _(satisfied: {r.satisfied})_\n\n"
        f"## Next\n{_bullets(r.next)}\n\n"
        f"## Map\n"
        f"- **keywords:** {', '.join(r.keywords) or '_(none)_'}\n"
        f"- **keyfiles:** {', '.join(r.keyfiles) or '_(none)_'}\n"
    )


# --------------------------------------------------------------- lessons --
def _write_lessons(lessons_dir: Path, index_path: Path, lessons: list[Lesson]) -> list[Path]:
    if not lessons:
        return []

    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    header, body = _split_header(existing)
    sections = _parse_sections(body)
    known = _known_slugs(existing)

    lessons_dir_resolved = lessons_dir.resolve()
    new_paths: list[Path] = []
    for lesson in lessons:
        if lesson.slug in known:
            continue
        lesson_path = lessons_dir / f"{lesson.slug}.md"
        # Fix 1 (defense-in-depth sink): resolve the candidate path and confirm
        # it stays inside lessons_dir.  _slugify at the source boundary should
        # have stripped any traversal sequences already; this is a last-resort
        # guard in case the slug somehow still resolves outside the directory.
        # Path.is_relative_to is available from Python 3.9+.
        if not lesson_path.resolve().is_relative_to(lessons_dir_resolved):
            continue
        if not lesson_path.exists():
            lesson_path.write_text(_render_lesson(lesson), encoding="utf-8")
            new_paths.append(lesson_path)
        line = f"- [{lesson.slug}.md]({lesson.slug}.md) — {lesson.rule}"
        sections.setdefault(lesson.category, []).append(line)
        known.add(lesson.slug)

    index_path.write_text(_render_index(header, sections), encoding="utf-8")
    return new_paths


def _render_lesson(lesson: Lesson) -> str:
    return f"# {lesson.slug}\n\n{lesson.rule}\n\n_Category: {lesson.category}_\n"


def _split_header(text: str) -> tuple[str, str]:
    """Preserve everything before the first `## ` section as the header."""
    if not text.strip():
        return _INDEX_HEADER, ""
    lines = text.splitlines()
    i = 0
    head: list[str] = []
    while i < len(lines) and not lines[i].startswith("## "):
        head.append(lines[i])
        i += 1
    header = ("\n".join(head).rstrip() + "\n") if any(h.strip() for h in head) else _INDEX_HEADER
    return header, "\n".join(lines[i:])


def _parse_sections(body: str) -> dict[str, list[str]]:
    """Ordered map of `## Category` -> its bullet lines."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif line.startswith("- ") and current is not None:
            sections[current].append(line)
    return sections


def _known_slugs(text: str) -> set[str]:
    return set(re.findall(r"\(([a-z0-9-]+)\.md\)", text))


def _render_index(header: str, sections: dict[str, list[str]]) -> str:
    parts = [header.rstrip() + "\n"]
    for category, lines in sections.items():
        if not lines:
            continue
        parts.append(f"## {category}\n")
        parts.append("\n".join(lines) + "\n")
    return "\n".join(parts).rstrip() + "\n"
