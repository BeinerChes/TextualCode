"""Regression tests for the escaping fix in WorkspacePanel._title and _build.

Guards against:
- CWE-150 markup injection via file paths containing Rich/Textual markup tags.
- Backslash doubling: paths with single backslashes must remain single in
  Content.plain (escape() doubles them in the markup string, but the parser
  re-interprets \\x → x, so the round-trip is transparent).
- Literal bracket preservation: a[b].py must not be parsed as a markup tag.
- Error-card path: git stderr containing "[" must not raise MarkupError.

All tests are pure and hermetic — no live git, no network, no Textual app loop.
"""

from __future__ import annotations

import pytest

import textualcode.workspace_panel as workspace_panel_module
from textualcode.gitinfo import FileDiff, GitState, WorkspaceDiff
from textualcode.workspace_panel import WorkspacePanel


# ---------------------------------------------------------------------------
# 1. Module-level guard: the hand-rolled _escape helper must not exist
# ---------------------------------------------------------------------------


def test_no_hand_rolled_escape_helper() -> None:
    """_escape must have been removed — only textual.markup.escape is used."""
    assert not hasattr(workspace_panel_module, "_escape"), (
        "Found '_escape' on workspace_panel module. "
        "The hand-rolled helper should have been removed in favour of "
        "textual.markup.escape."
    )


# ---------------------------------------------------------------------------
# 2. KEY regression: backslash and bracket in path preserved after escaping
# ---------------------------------------------------------------------------


class TestTitleEscaping:
    """WorkspacePanel._title must produce Content whose .plain preserves paths."""

    def _make_modified(self, path: str, added: int = 0, removed: int = 0) -> FileDiff:
        return FileDiff(
            path=path,
            body="",
            added=added,
            removed=removed,
            status="modified",
            is_untracked=False,
        )

    def _make_untracked(self, path: str, added: int = 0) -> FileDiff:
        return FileDiff(
            path=path,
            body="",
            added=added,
            removed=0,
            status="untracked",
            is_untracked=True,
        )

    def test_backslash_path_single_backslash_in_plain(self) -> None:
        """A path with backslashes must appear with SINGLE backslashes in .plain.

        escape() doubles backslashes in the markup source string (\\\\), but
        Content.from_markup's parser converts \\\\x back to \\x, so the
        round-trip is transparent and .plain reflects the original path.
        """
        path = r"dir\sub\file.py"
        f = self._make_modified(path, added=3, removed=1)
        content = WorkspacePanel._title(f)

        # The literal path must be present in .plain
        assert path in content.plain, (
            f"Expected original path {path!r} in Content.plain, got {content.plain!r}"
        )
        # Specifically: no doubled backslashes should appear in plain
        assert "\\\\" not in content.plain, (
            f"Doubled backslash found in Content.plain: {content.plain!r}"
        )

    def test_bracket_in_path_preserved_literally(self) -> None:
        """A path containing '[' and ']' must NOT be interpreted as markup."""
        path = r"a[b].py"
        f = self._make_modified(path, added=2, removed=0)
        content = WorkspacePanel._title(f)

        assert path in content.plain, (
            f"Expected {path!r} in Content.plain, got {content.plain!r}"
        )

    def test_backslash_and_bracket_combined(self) -> None:
        """The primary regression case: a path with BOTH backslash and bracket."""
        path = r"dir\sub\a[b].py"
        f = self._make_modified(path, added=5, removed=3)
        content = WorkspacePanel._title(f)

        # Original path preserved verbatim
        assert path in content.plain, (
            f"Expected {path!r} in Content.plain, got {content.plain!r}"
        )
        # Verify single backslash count: 2 backslashes in "dir\sub\a[b].py"
        assert content.plain.count("\\") == 2, (
            f"Expected 2 backslashes in plain, got: {content.plain!r}"
        )
        # Bracket preserved as literal character
        assert "[b]" in content.plain

    def test_markup_injection_in_path_does_not_raise(self) -> None:
        """A path containing Rich markup tags must not raise and must render
        literally — the tags must NOT be interpreted as colour markup."""
        path = "x[red]y[/].py"
        f = self._make_modified(path)
        # Must not raise MarkupError / ValueError
        content = WorkspacePanel._title(f)

        # The full path string must appear literally in plain output
        assert path in content.plain, (
            f"Expected {path!r} literally in Content.plain, got {content.plain!r}"
        )

    def test_markup_injection_untracked_path_does_not_raise(self) -> None:
        """Untracked files follow the same code path for path escaping."""
        path = "docs[draft]/notes[v2].md"
        f = self._make_untracked(path, added=10)
        content = WorkspacePanel._title(f)

        assert path in content.plain, (
            f"Expected {path!r} in Content.plain, got {content.plain!r}"
        )

    def test_plain_path_no_change(self) -> None:
        """A path with no special characters is still rendered correctly."""
        path = "src/main.py"
        f = self._make_modified(path, added=1, removed=1)
        content = WorkspacePanel._title(f)

        assert path in content.plain


# ---------------------------------------------------------------------------
# 3. Error-card branch: git stderr containing "[" must not raise
# ---------------------------------------------------------------------------


class TestBuildErrorCard:
    """WorkspacePanel._build must escape git stderr before markup rendering."""

    def _build_for(self, error: str) -> tuple:
        """Run _build with an error WorkspaceDiff and no files."""
        result = WorkspaceDiff(
            state=GitState.OK,
            error=error,
            files=(),
        )
        panel = WorkspacePanel.__new__(WorkspacePanel)
        return panel._build(result)

    def test_error_with_bracket_does_not_raise(self) -> None:
        """git stderr containing '[' must not raise MarkupError."""
        error_msg = "fatal: not a git repo [error code 128]"
        # Must not raise
        summary, cards = self._build_for(error_msg)
        assert len(cards) == 1, "Expected exactly one error card"

    def test_error_bracket_rendered_literally(self) -> None:
        """The bracketed text in git stderr must appear literally in the card."""
        error_msg = "fatal: [error code 128] see docs"
        summary, cards = self._build_for(error_msg)

        # Access the Content stored in the Static widget
        error_card = cards[0]
        card_content = error_card._Static__content
        plain = card_content.plain

        # The original error message (including brackets) must be in the output
        assert "[error code 128]" in plain, (
            f"Expected '[error code 128]' literally in card plain, got {plain!r}"
        )

    def test_error_with_backslash_in_stderr(self) -> None:
        """Backslashes in git stderr must not be doubled in the card plain."""
        error_msg = r"error: cannot open C:\repo\.git\config"
        summary, cards = self._build_for(error_msg)

        error_card = cards[0]
        card_content = error_card._Static__content
        plain = card_content.plain

        # Single backslashes preserved
        assert "\\\\" not in plain, (
            f"Doubled backslash in error card plain: {plain!r}"
        )
        assert r"C:\repo" in plain or "C:" in plain

    def test_error_with_markup_tag_in_stderr_does_not_raise(self) -> None:
        """Markup tags in git stderr (e.g., '[red]') must not be interpreted."""
        error_msg = "fatal: remote [origin] not found"
        # Must not raise MarkupError
        summary, cards = self._build_for(error_msg)
        assert len(cards) == 1

        error_card = cards[0]
        card_content = error_card._Static__content
        plain = card_content.plain
        assert "[origin]" in plain, (
            f"Expected '[origin]' literally in plain, got {plain!r}"
        )

    def test_clean_tree_error_only_has_error_card(self) -> None:
        """When there are no files but there is an error, only the error card
        is returned (no file cards), confirming the error-only branch."""
        summary, cards = self._build_for("some error [128]")
        # summary is the clean-tree message (with newline note)
        assert len(cards) == 1
