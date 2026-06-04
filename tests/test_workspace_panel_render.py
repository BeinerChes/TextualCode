"""Render-correctness tests for WorkspacePanel._file_body after the
ClassNotFound-removal / Syntax-fallback fix.

All tests are pure and hermetic — no live git, no network, no Textual app loop.

Coverage
--------
1. `ClassNotFound` import from pygments.util is gone from the module (it now
   only appears in comments, if at all, but not as an actual import or in a
   try/except block).
2. `_file_body` returns a Static for a known lexer name ("python") without
   raising.
3. `_file_body` returns a Static for a completely bogus lexer name without
   raising — Rich 15.0.0 resolves lexers lazily and falls back gracefully.
4. `_file_body` with an empty body returns the "(no preview)" Static.
5. `_file_body` with a whitespace-only body returns the "(no preview)" Static
   (the guard is `body.strip()`, not `body`).
6. The Static returned for a non-empty body wraps a Rich Syntax instance
   (confirmed via Static.content — the public property in Textual 8.2.7).
7. The Syntax's `_lexer` attribute matches the lexer string that was passed in
   (constructor stores it verbatim; resolution is deferred).
"""

from __future__ import annotations

import ast

import pytest
from rich.syntax import Syntax
from rich.text import Text
from textual.widgets import Static

import textualcode.workspace_panel as workspace_panel_module
from textualcode.gitinfo import FileDiff
from textualcode.workspace_panel import WorkspacePanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(
    body: str,
    lexer: str = "diff",
    path: str = "test_file.py",
    is_untracked: bool = False,
) -> FileDiff:
    """Construct a minimal FileDiff stub for _file_body tests."""
    return FileDiff(
        path=path,
        body=body,
        lexer=lexer,
        is_untracked=is_untracked,
    )


# ---------------------------------------------------------------------------
# 1.  ClassNotFound is NOT imported from the module
# ---------------------------------------------------------------------------


def test_no_pygments_classnotfound_import() -> None:
    """pygments.util.ClassNotFound must not be imported in workspace_panel.

    The fix replaced an explicit try/except ClassNotFound block with Rich's
    built-in lazy-fallback; the import must therefore be absent from the module.
    Check at the AST level so even a conditional / `__all__` import is caught.
    """
    import pathlib

    src = pathlib.Path(workspace_panel_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            if "pygments" in module and "ClassNotFound" in names:
                pytest.fail(
                    f"Found 'from {module} import ... ClassNotFound' in "
                    f"workspace_panel.py — the import should have been removed "
                    f"after the Rich lazy-fallback fix."
                )

        if isinstance(node, ast.Import):
            for alias in node.names:
                if "pygments" in (alias.name or ""):
                    # Bare 'import pygments.*' is very unlikely but guard it too
                    pass  # not a ClassNotFound import; leave unchecked


def test_no_try_except_in_module() -> None:
    """workspace_panel.py must contain no try/except blocks.

    Before the fix, _file_body wrapped Syntax() in a try/except ClassNotFound.
    After the fix that block is gone; assert no try-node exists in the AST.
    """
    import pathlib

    src = pathlib.Path(workspace_panel_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    try_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    assert not try_nodes, (
        f"Found {len(try_nodes)} try/except block(s) in workspace_panel.py — "
        "the ClassNotFound try/except should have been removed in the fix."
    )


# ---------------------------------------------------------------------------
# 2 & 3.  _file_body returns Static for known AND bogus lexer names
# ---------------------------------------------------------------------------


class TestFileBodyLexerFallback:
    """_file_body must return Static without raising for any lexer name.

    Rich 15.0.0 resolves the lexer lazily in Syntax.lexer (the property), so
    an unknown name never raises at construction time.
    """

    def test_known_lexer_returns_static(self) -> None:
        """A well-known lexer name ('python') must yield a Static without raising."""
        f = _make_file(body="x = 1\n", lexer="python")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result, Static), (
            f"Expected Static, got {type(result).__name__}"
        )

    def test_known_lexer_does_not_raise(self) -> None:
        """Constructing _file_body with 'python' must not raise any exception."""
        f = _make_file(body="def foo(): pass\n", lexer="python")
        # If this raises, the test fails — no try/except in test by design.
        WorkspacePanel._file_body(f)

    def test_bogus_lexer_returns_static(self) -> None:
        """An entirely unknown lexer name must still yield a Static, not raise."""
        f = _make_file(body="some content\n", lexer="totally-bogus-lexer")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result, Static), (
            f"Expected Static even for bogus lexer, got {type(result).__name__}"
        )

    def test_bogus_lexer_does_not_raise(self) -> None:
        """Constructing _file_body with an unknown lexer must not raise."""
        f = _make_file(body="anything\n", lexer="totally-bogus-lexer")
        # Rich defers lexer resolution; no exception at this point.
        WorkspacePanel._file_body(f)

    def test_diff_lexer_returns_static(self) -> None:
        """The default 'diff' lexer (used for tracked changes) must yield Static."""
        f = _make_file(
            body="diff --git a/x.py b/x.py\n+added line\n-removed line\n",
            lexer="diff",
        )
        result = WorkspacePanel._file_body(f)
        assert isinstance(result, Static)


# ---------------------------------------------------------------------------
# 4 & 5.  _file_body with empty / whitespace-only body → "(no preview)"
# ---------------------------------------------------------------------------


class TestFileBodyEmptyContent:
    """_file_body guards against empty/whitespace bodies and returns a placeholder."""

    def _get_plain(self, result: Static) -> str:
        """Return the plain text of the Static widget's content."""
        content = result.content
        # Static.content is a public property in Textual 8.2.7 that returns
        # either a Text, Syntax, or other renderable stored in _Static__content.
        if isinstance(content, Text):
            return content.plain
        # Fallback: str() for other renderable types
        return str(content)

    def test_empty_body_returns_static(self) -> None:
        """An empty body string must return a Static (the no-preview placeholder)."""
        f = _make_file(body="")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result, Static)

    def test_empty_body_has_no_preview_text(self) -> None:
        """The Static for an empty body must display '(no preview)'."""
        f = _make_file(body="")
        result = WorkspacePanel._file_body(f)
        plain = self._get_plain(result)
        assert "(no preview)" in plain, (
            f"Expected '(no preview)' in empty-body Static, got {plain!r}"
        )

    def test_whitespace_only_body_returns_static(self) -> None:
        """A whitespace-only body ('  \\n  ') must also yield the placeholder."""
        f = _make_file(body="   \n  \t  ")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result, Static)

    def test_whitespace_only_body_has_no_preview_text(self) -> None:
        """The Static for a whitespace-only body must display '(no preview)'."""
        f = _make_file(body="   \n  \t  ")
        result = WorkspacePanel._file_body(f)
        plain = self._get_plain(result)
        assert "(no preview)" in plain, (
            f"Expected '(no preview)' in whitespace-body Static, got {plain!r}"
        )

    def test_single_newline_body_is_no_preview(self) -> None:
        """A body of a single newline is whitespace-only and must show '(no preview)'."""
        f = _make_file(body="\n")
        result = WorkspacePanel._file_body(f)
        plain = self._get_plain(result)
        assert "(no preview)" in plain

    def test_nonempty_body_is_not_no_preview(self) -> None:
        """A body with actual content must NOT return the no-preview placeholder."""
        f = _make_file(body="print('hello')\n", lexer="python")
        result = WorkspacePanel._file_body(f)
        plain = self._get_plain(result)
        assert "(no preview)" not in plain, (
            f"Non-empty body should not show '(no preview)', but got {plain!r}"
        )


# ---------------------------------------------------------------------------
# 6.  Non-empty body wraps a Rich Syntax instance
# ---------------------------------------------------------------------------


class TestFileBodySyntaxContent:
    """For a non-empty body, _file_body must store a Rich Syntax in Static.content."""

    def test_content_is_syntax_for_known_lexer(self) -> None:
        """Static.content must be a Rich Syntax for a known lexer name."""
        f = _make_file(body="x = 1\n", lexer="python")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result.content, Syntax), (
            f"Expected Static.content to be rich.syntax.Syntax, got "
            f"{type(result.content).__name__}"
        )

    def test_content_is_syntax_for_bogus_lexer(self) -> None:
        """Static.content must be a Rich Syntax even when the lexer name is bogus."""
        f = _make_file(body="some text\n", lexer="totally-bogus-lexer")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result.content, Syntax), (
            f"Expected Static.content to be Syntax for bogus lexer, got "
            f"{type(result.content).__name__}"
        )

    def test_syntax_stores_lexer_verbatim(self) -> None:
        """Rich Syntax stores the lexer name verbatim in _lexer at construction.

        Resolution is deferred; the stored value must match what was passed in.
        Verified against installed Rich 15.0.0 source.
        """
        f = _make_file(body="x = 1\n", lexer="python")
        result = WorkspacePanel._file_body(f)
        syntax = result.content
        assert isinstance(syntax, Syntax)
        assert syntax._lexer == "python", (
            f"Expected Syntax._lexer == 'python', got {syntax._lexer!r}"
        )

    def test_syntax_stores_bogus_lexer_verbatim(self) -> None:
        """Even a bogus lexer name is stored verbatim in Syntax._lexer."""
        f = _make_file(body="whatever\n", lexer="totally-bogus-lexer")
        result = WorkspacePanel._file_body(f)
        syntax = result.content
        assert isinstance(syntax, Syntax)
        assert syntax._lexer == "totally-bogus-lexer", (
            f"Expected Syntax._lexer == 'totally-bogus-lexer', got {syntax._lexer!r}"
        )

    def test_empty_body_content_is_not_syntax(self) -> None:
        """The no-preview placeholder must NOT store a Syntax — it uses rich.text.Text."""
        f = _make_file(body="")
        result = WorkspacePanel._file_body(f)
        assert not isinstance(result.content, Syntax), (
            "The '(no preview)' Static must not use Syntax — it should be Text."
        )

    def test_empty_body_content_is_text(self) -> None:
        """The no-preview placeholder must store a rich.text.Text instance."""
        f = _make_file(body="")
        result = WorkspacePanel._file_body(f)
        assert isinstance(result.content, Text), (
            f"Expected rich.text.Text for no-preview body, got "
            f"{type(result.content).__name__}"
        )
