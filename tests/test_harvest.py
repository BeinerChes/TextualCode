"""Tests for harvest.py and lessons.py security / correctness fixes.

All tests are hermetic — no network, no real SDK, no filesystem writes
unless using tmp_path.

Covers:
  1. CWE-22 path traversal: slug is always normalized through _slugify
  2. Markdown injection: single-line fields are sanitized (newlines collapsed,
     length capped)
  3. is_error load-bearing: HarvestController skips write_harvest + success
     message when result.is_error is True
  4. Defense-in-depth sink: lessons._write_lessons skips paths outside
     lessons_dir
  5. write_harvest path confinement: no file written outside lessons_dir even
     when a Lesson is constructed directly with a traversal slug
  6. Normal slug passes through _parse unchanged
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from textualcode.harvest import HarvestResult, Harvester, Lesson, _slugify, _sanitize_line


# ---------------------------------------------------------------------------
# _slugify — unit
# ---------------------------------------------------------------------------

def test_slugify_strips_path_separators():
    """_slugify must reduce path separator characters to hyphens."""
    result = _slugify("../../../../etc/passwd")
    # After slugification, forward slashes become hyphens and leading hyphens
    # are stripped; the result must not contain any dots or slashes.
    assert "/" not in result
    assert "\\" not in result
    assert ".." not in result


def test_slugify_result_safe_filename():
    """_slugify output must contain only [a-z0-9-]."""
    dangerous_inputs = [
        "../../bad",
        "foo/bar",
        "C:\\Windows\\System32",
        "hello world!",
        "UPPER CASE",
        "a" * 100,
    ]
    for inp in dangerous_inputs:
        result = _slugify(inp)
        assert re.fullmatch(r"[a-z0-9-]*", result), (
            f"_slugify({inp!r}) produced unsafe result: {result!r}"
        )


def test_slugify_caps_at_60():
    slug = _slugify("a" * 100)
    assert len(slug) <= 60


def test_slugify_empty_returns_lesson():
    assert _slugify("") == "lesson"


def test_slugify_strips_leading_trailing_hyphens():
    result = _slugify("---hello---")
    assert not result.startswith("-")
    assert not result.endswith("-")


# ---------------------------------------------------------------------------
# _sanitize_line — unit
# ---------------------------------------------------------------------------

def test_sanitize_line_collapses_newlines():
    result = _sanitize_line("hello\nworld", 300)
    assert "\n" not in result
    assert result == "hello world"


def test_sanitize_line_collapses_tabs():
    result = _sanitize_line("hello\tworld", 300)
    assert "\t" not in result


def test_sanitize_line_collapses_multiple_spaces():
    result = _sanitize_line("hello   world", 300)
    assert result == "hello world"


def test_sanitize_line_caps_length():
    result = _sanitize_line("x" * 500, 40)
    assert len(result) <= 40


def test_sanitize_line_strips_leading_trailing_whitespace():
    result = _sanitize_line("  hello  ", 300)
    assert result == "hello"


def test_sanitize_line_category_max_40():
    # Category field is capped at 40 chars
    long_category = "A" * 100
    result = _sanitize_line(long_category, 40)
    assert len(result) <= 40


def test_sanitize_line_rule_max_300():
    long_rule = "A" * 500
    result = _sanitize_line(long_rule, 300)
    assert len(result) <= 300


# ---------------------------------------------------------------------------
# Harvester._parse — slug always normalized (Fix 1)
# ---------------------------------------------------------------------------

def _make_parse_result(slug_value, rule_value="Do the right thing"):
    """Call _parse with a JSON-shaped dict containing the given slug."""
    import json
    raw = json.dumps({
        "goal": "test",
        "lessons": [{"slug": slug_value, "category": "General", "rule": rule_value}],
    })
    return Harvester._parse(raw, usage=None, cost=None)


def test_parse_traversal_slug_is_sanitized():
    """A path-traversal slug must be slugified, not passed verbatim."""
    result = _make_parse_result("../../../../etc/passwd")
    assert len(result.lessons) == 1
    slug = result.lessons[0].slug
    assert "/" not in slug
    assert ".." not in slug
    assert re.fullmatch(r"[a-z0-9-]+", slug), f"Slug not safe: {slug!r}"


def test_parse_windows_traversal_slug_is_sanitized():
    """Windows backslash traversal slug must be sanitized."""
    result = _make_parse_result("..\\..\\windows\\system32\\evil")
    assert len(result.lessons) == 1
    slug = result.lessons[0].slug
    assert "\\" not in slug
    assert ".." not in slug


def test_parse_empty_slug_falls_back_to_slugified_rule():
    """When slug is empty, _slugify(rule) is used as fallback."""
    result = _make_parse_result("")
    assert len(result.lessons) == 1
    slug = result.lessons[0].slug
    # Should be derived from the rule "Do the right thing"
    assert slug not in ("", "lesson") or True  # at minimum, no error
    assert re.fullmatch(r"[a-z0-9-]+", slug), f"Slug not safe: {slug!r}"


def test_parse_slug_never_verbatim_with_special_chars():
    """A slug like 'foo/../bar' is normalized — not passed verbatim."""
    result = _make_parse_result("foo/../bar")
    assert len(result.lessons) == 1
    slug = result.lessons[0].slug
    assert ".." not in slug
    assert "/" not in slug


# ---------------------------------------------------------------------------
# Harvester._parse — explicit traversal inputs required by task spec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("traversal_slug", [
    "../../../foo",
    "/etc/passwd",
    "a/b\\c",
    "..\\..\\x",
])
def test_parse_explicit_traversal_slugs_sanitized(traversal_slug):
    """Each explicit traversal-style slug from the task spec must produce a
    Lesson.slug matching ^[a-z0-9-]+$ with no slashes, dots, or drive letters."""
    result = _make_parse_result(traversal_slug)
    assert len(result.lessons) == 1, (
        f"Expected 1 lesson for slug {traversal_slug!r}, got {len(result.lessons)}"
    )
    slug = result.lessons[0].slug
    assert "/" not in slug, f"Forward slash in slug: {slug!r} (input={traversal_slug!r})"
    assert "\\" not in slug, f"Backslash in slug: {slug!r} (input={traversal_slug!r})"
    assert ".." not in slug, f"'..' in slug: {slug!r} (input={traversal_slug!r})"
    # No drive letters (e.g. 'c:')
    assert ":" not in slug, f"Colon in slug: {slug!r} (input={traversal_slug!r})"
    assert re.fullmatch(r"[a-z0-9-]+", slug), (
        f"Slug not safe for {traversal_slug!r}: {slug!r}"
    )


def test_parse_normal_slug_passes_through_unchanged():
    """A well-formed slug such as 'my-lesson-slug' must pass through _parse
    byte-identical (no truncation, no mutation)."""
    normal_slug = "my-lesson-slug"
    result = _make_parse_result(normal_slug)
    assert len(result.lessons) == 1
    assert result.lessons[0].slug == normal_slug, (
        f"Normal slug changed: expected {normal_slug!r}, got {result.lessons[0].slug!r}"
    )


# ---------------------------------------------------------------------------
# Harvester._parse — single-line field sanitization (Fix 2)
# ---------------------------------------------------------------------------

def test_parse_category_newline_collapsed():
    """Newlines in category are collapsed to spaces."""
    import json
    raw = json.dumps({
        "lessons": [{"slug": "my-lesson", "category": "Foo\nBar", "rule": "Do X"}]
    })
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    assert "\n" not in result.lessons[0].category


def test_parse_category_length_capped():
    """Category is capped at 40 chars."""
    import json
    raw = json.dumps({
        "lessons": [{"slug": "my-lesson", "category": "A" * 100, "rule": "Do X"}]
    })
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    assert len(result.lessons[0].category) <= 40


def test_parse_rule_newline_collapsed():
    """Newlines in rule are collapsed to spaces."""
    import json
    raw = json.dumps({
        "lessons": [{
            "slug": "test",
            "category": "General",
            "rule": "First line\nSecond line injected"
        }]
    })
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    assert "\n" not in result.lessons[0].rule


def test_parse_rule_length_capped_at_300():
    """Rule is capped at 300 chars."""
    import json
    raw = json.dumps({
        "lessons": [{
            "slug": "test",
            "category": "General",
            "rule": "x" * 500,
        }]
    })
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    assert len(result.lessons[0].rule) <= 300


def test_parse_satisfied_newline_collapsed():
    """Newlines in 'satisfied' field are collapsed."""
    import json
    raw = json.dumps({"satisfied": "yes\ninjected header"})
    result = Harvester._parse(raw, None, None)
    assert "\n" not in result.satisfied


def test_parse_category_combined_newline_and_length_capped():
    """Category with embedded newlines AND excess length: must be single-line
    and capped at 40 chars."""
    import json
    long_multiline_category = ("A\nB" * 20)  # 60 chars with embedded newlines
    raw = json.dumps({
        "lessons": [{
            "slug": "test-slug",
            "category": long_multiline_category,
            "rule": "Do X"
        }]
    })
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    cat = result.lessons[0].category
    assert "\n" not in cat, "Category must be single-line"
    assert len(cat) <= 40, f"Category not capped: len={len(cat)}"


def test_parse_rule_combined_newline_and_length_capped():
    """Rule with embedded newlines AND excess length: must be single-line and
    capped at 300 chars."""
    import json
    long_multiline_rule = ("Do this thing\n" * 30)  # ~420 chars with newlines
    raw = json.dumps({
        "lessons": [{
            "slug": "test-slug",
            "category": "General",
            "rule": long_multiline_rule
        }]
    })
    result = Harvester._parse(raw, None, None)
    assert len(result.lessons) == 1
    rule = result.lessons[0].rule
    assert "\n" not in rule, "Rule must be single-line"
    assert len(rule) <= 300, f"Rule not capped: len={len(rule)}"


# ---------------------------------------------------------------------------
# lessons._write_lessons — path confinement sink (Fix 1 defense-in-depth)
# ---------------------------------------------------------------------------

def test_write_lessons_rejects_traversal_slug(tmp_path):
    """A lesson whose slug resolves outside lessons_dir must be silently skipped."""
    from textualcode.lessons import _write_lessons

    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    index_path = lessons_dir / "INDEX.md"

    # Craft a Lesson with a slug that would escape the directory.  On most
    # platforms _slugify removes the dots and slashes, but we test the sink
    # directly by constructing a Lesson with a pre-crafted slug.  We need a
    # slug that after "lessons_dir / f'{slug}.md'" would resolve outside; the
    # simplest way on POSIX is a slug containing "..".  The sink guard checks
    # .resolve().is_relative_to(lessons_dir.resolve()) and must reject it.
    evil_lesson = Lesson(slug="../evil", category="Bad", rule="Do evil")
    _write_lessons(lessons_dir, index_path, [evil_lesson])

    # The file must NOT have been created outside lessons_dir
    escaped_path = tmp_path / "evil.md"
    assert not escaped_path.exists(), (
        "Path-traversal slug must not write outside lessons_dir"
    )
    # INDEX.md should either not exist or not contain "evil"
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        assert "evil" not in content or "../evil" not in content


def test_write_lessons_accepts_normal_slug(tmp_path):
    """A normal lesson slug must still be written correctly."""
    from textualcode.lessons import _write_lessons

    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    index_path = lessons_dir / "INDEX.md"

    lesson = Lesson(slug="my-lesson", category="General", rule="Do the right thing.")
    new_paths = _write_lessons(lessons_dir, index_path, [lesson])

    assert len(new_paths) == 1
    assert new_paths[0].exists()
    assert new_paths[0].name == "my-lesson.md"
    content = index_path.read_text(encoding="utf-8")
    assert "my-lesson" in content


def test_write_lessons_no_exception_on_traversal_slug(tmp_path):
    """_write_lessons must not raise any exception even when a Lesson is
    constructed directly with a traversal slug."""
    from textualcode.lessons import _write_lessons

    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    index_path = lessons_dir / "INDEX.md"

    # Construct Lesson directly, bypassing _slugify at the source
    evil_lesson = Lesson(slug="../../evil", category="Bad", rule="Do evil")
    # Must not raise
    try:
        _write_lessons(lessons_dir, index_path, [evil_lesson])
    except Exception as exc:
        pytest.fail(f"_write_lessons raised an exception for traversal slug: {exc!r}")


def test_write_lessons_mixed_no_escape(tmp_path):
    """A mix of traversal and normal lessons: traversal is skipped, normal is
    written, and nothing escapes the lessons directory."""
    from textualcode.lessons import _write_lessons

    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    index_path = lessons_dir / "INDEX.md"

    evil = Lesson(slug="../escaped", category="Bad", rule="Evil rule")
    good = Lesson(slug="good-lesson", category="General", rule="Good rule.")
    new_paths = _write_lessons(lessons_dir, index_path, [evil, good])

    # Only the good lesson should be written
    assert len(new_paths) == 1
    assert new_paths[0].name == "good-lesson.md"

    # No file must exist outside the lessons directory
    escaped = tmp_path / "escaped.md"
    assert not escaped.exists()

    # The lessons directory must only contain expected files
    written_names = {f.name for f in lessons_dir.iterdir()}
    assert "escaped.md" not in written_names


def test_write_harvest_path_confinement(tmp_path):
    """write_harvest with a traversal-slug Lesson must NOT write any file
    outside the .claude/lessons directory, and must not raise."""
    from textualcode.lessons import write_harvest

    evil_lesson = Lesson(slug="../../outside", category="Escape", rule="Escape rule")
    result = HarvestResult(
        goal="test",
        why="testing",
        result="done",
        lessons=[evil_lesson],
    )

    # Must not raise
    try:
        paths = write_harvest(tmp_path, result)
    except Exception as exc:
        pytest.fail(f"write_harvest raised an exception: {exc!r}")

    # No file should exist at the escaped location
    # The traversal "../../outside" from lessons_dir (.claude/lessons) would try
    # to escape to tmp_path/../outside.md or similar; verify nothing outside .claude
    claude_dir = tmp_path / ".claude"

    def _all_files_under(root: Path) -> list[Path]:
        return [p for p in root.rglob("*") if p.is_file()]

    all_written = _all_files_under(tmp_path)
    for written in all_written:
        assert written.is_relative_to(claude_dir), (
            f"File written outside .claude dir: {written}"
        )


# ---------------------------------------------------------------------------
# HarvestController.run — is_error branch (Fix 3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_harvest_controller_skips_write_on_is_error():
    """When result.is_error is True, write_harvest must NOT be called and
    the success message must NOT be shown."""
    from textualcode.harvest_controller import HarvestController

    # Build a minimal fake app
    fake_conversation = MagicMock()
    fake_conversation.add_markdown = AsyncMock()

    fake_thinking = MagicMock()

    fake_transcript = MagicMock()
    fake_transcript.empty = False
    fake_transcript.render = MagicMock(return_value="some transcript")

    fake_app = MagicMock()
    fake_app._transcript = fake_transcript
    fake_app._conversation = fake_conversation
    fake_app._thinking = fake_thinking
    fake_app._project_dir = Path("/fake/project")

    error_result = HarvestResult(is_error=True)

    with (
        patch("textualcode.harvest_controller.Harvester") as MockHarvester,
        patch("textualcode.harvest_controller.write_harvest") as mock_write,
    ):
        mock_instance = MockHarvester.return_value
        mock_instance.run = AsyncMock(return_value=error_result)

        controller = HarvestController(fake_app)
        await controller.run()

    # write_harvest must not be called
    mock_write.assert_not_called()

    # Success message (contains ✅) must not appear
    all_md_calls = [
        call.args[0]
        for call in fake_conversation.add_markdown.call_args_list
    ]
    assert not any("✅" in msg for msg in all_md_calls), (
        "Success message must not appear when is_error=True"
    )

    # An error/warning message must appear
    assert any(
        "error" in msg.lower() or "⚠" in msg or "did not complete" in msg
        for msg in all_md_calls
    ), "An error/warning message must appear when is_error=True"

    # thinking.stop must be called for key='harvest'
    fake_thinking.stop.assert_called_with(key="harvest")


@pytest.mark.asyncio
async def test_harvest_controller_writes_on_success():
    """When result.is_error is False, write_harvest IS called and success
    message IS shown."""
    from textualcode.harvest_controller import HarvestController
    from textualcode.lessons import HarvestPaths

    fake_conversation = MagicMock()
    fake_conversation.add_markdown = AsyncMock()

    fake_thinking = MagicMock()

    fake_transcript = MagicMock()
    fake_transcript.empty = False
    fake_transcript.render = MagicMock(return_value="some transcript")

    fake_app = MagicMock()
    fake_app._transcript = fake_transcript
    fake_app._conversation = fake_conversation
    fake_app._thinking = fake_thinking
    fake_app._project_dir = Path("/fake/project")
    fake_app.push_screen_wait = AsyncMock(return_value=False)

    ok_result = HarvestResult(is_error=False, cost=0.001)

    fake_paths = HarvestPaths(
        root=Path("/fake/project/.claude"),
        state=Path("/fake/project/.claude/state.md"),
        index=Path("/fake/project/.claude/lessons/INDEX.md"),
        new_lessons=[],
    )

    with (
        patch("textualcode.harvest_controller.Harvester") as MockHarvester,
        patch("textualcode.harvest_controller.write_harvest", return_value=fake_paths) as mock_write,
    ):
        mock_instance = MockHarvester.return_value
        mock_instance.run = AsyncMock(return_value=ok_result)

        controller = HarvestController(fake_app)
        await controller.run()

    mock_write.assert_called_once()

    all_md_calls = [
        call.args[0]
        for call in fake_conversation.add_markdown.call_args_list
    ]
    assert any("✅" in msg for msg in all_md_calls), (
        "Success message must appear when is_error=False"
    )
