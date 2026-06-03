"""Toggleable workspace panel — a tabbed view of the working tree.

Currently a single tab, **Diff**: a snapshot of uncommitted changes
(`git diff HEAD` plus untracked files), rendered GitHub-style as a summary
header over a list of **collapsible, per-file** cards. Each card's title shows
a status badge, the path, and a colorized ``+added −removed`` count; expanding
it reveals that file's syntax-highlighted diff (or, for an untracked file, a
content preview). The git subprocess runs in a worker thread (off the UI loop)
and only when the panel is shown — the "on-demand" refresh model, so there is
zero background cost and the UI never stutters.

The container is a `TabbedContent` on purpose: a future **Files** tree tab can
be added alongside Diff without restructuring.

Git-awareness is defensive — the Diff tab renders a friendly placeholder when
git is not installed or the directory is not a repository, and never errors.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pygments.util import ClassNotFound
from rich.syntax import Syntax
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.content import Content
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Button,
    Collapsible,
    Static,
    TabbedContent,
    TabPane,
)

from . import gitinfo
from .groups import WORKSPACE

# Status -> (badge glyph, markup colour) for the per-file collapsible titles.
_STATUS_BADGE = {
    "modified": ("◆", "yellow"),
    "new": ("✚", "green"),
    "deleted": ("✕", "red"),
    "renamed": ("➜", "cyan"),
    "binary": ("⬡", "magenta"),
    "untracked": ("✚", "green"),
}


class WorkspacePanel(Vertical):
    """Left-side toggleable panel showing the working tree (Diff tab for now)."""

    BORDER_TITLE = "🌿 workspace"
    # 'r' refreshes; only fires while the panel (or a child) holds focus, so it
    # never shadows typing 'r' in the prompt input.
    BINDINGS = [("r", "refresh", "Refresh")]

    # Whether the panel is blown up to fill the whole tab. Toggled by the
    # ⛶ button; a watcher applies the `.expanded` style class and tells the app
    # to hide its siblings (conversation + sidebar) via `ExpandToggled`.
    # init=False so the message isn't posted before the panel is mounted.
    expanded: reactive[bool] = reactive(False, init=False)

    class ExpandToggled(Message):
        """Posted when the user toggles full-tab-size expansion."""

        def __init__(self, expanded: bool) -> None:
            super().__init__()
            self.expanded = expanded

    class ReviewRequested(Message):
        """Posted when the user presses the Review button.

        Orchestration lives on the app (it needs the agent/conversation), so the
        panel just announces the intent and the app runs the review worker.
        """

    class CommitRequested(Message):
        """Posted when the user presses the Commit button."""

    def __init__(self, cwd: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cwd = cwd

    def compose(self) -> ComposeResult:
        # Top action bar: Review / Commit stubs, plus the full-size toggle.
        with Horizontal(id="workspace-actions"):
            yield Button("Review", id="ws-review", variant="primary")
            yield Button("Commit", id="ws-commit", variant="success")
            yield Button("⛶", id="ws-expand", variant="default")
        with TabbedContent(id="workspace-tabs"):
            with TabPane("Diff", id="tab-diff"):
                with ScrollableContainer(id="diff-scroll"):
                    yield Static(id="diff-summary")
                    yield Vertical(id="diff-files")

    # -- public API ---------------------------------------------------------
    def action_refresh(self) -> None:
        """Keybinding target ('r')."""
        self.refresh_diff()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route the action-bar buttons.

        Review/Commit post messages the app handles (they need the agent and the
        conversation); the expand toggle is purely local to the panel.
        """
        event.stop()
        if event.button.id == "ws-expand":
            self.expanded = not self.expanded
        elif event.button.id == "ws-review":
            self.post_message(self.ReviewRequested())
        elif event.button.id == "ws-commit":
            self.post_message(self.CommitRequested())

    def watch_expanded(self, expanded: bool) -> None:
        """Apply the full-size style class and notify the app to reflow."""
        self.set_class(expanded, "expanded")
        button = self.query_one("#ws-expand", Button)
        button.label = "⮌" if expanded else "⛶"
        button.tooltip = "Restore panel size" if expanded else "Expand to full tab"
        self.post_message(self.ExpandToggled(expanded))

    @work(exclusive=True, group=WORKSPACE)
    async def refresh_diff(self) -> None:
        """Recompute the diff in a worker thread and re-render.

        Exclusive in the WORKSPACE group: a rapid re-toggle cancels the prior
        run instead of racing two git subprocesses onto the same widget.
        """
        summary = self.query_one("#diff-summary", Static)
        files_box = self.query_one("#diff-files", Vertical)
        summary.update(Text("Loading diff…", style="dim italic"))
        result = await asyncio.to_thread(gitinfo.workspace_diff, self._cwd)

        await files_box.remove_children()
        summary_text, cards = self._build(result)
        summary.update(summary_text)
        if cards:
            await files_box.mount_all(cards)

    # -- rendering ----------------------------------------------------------
    # NOTE: do NOT name this `_render` — that shadows Widget._render and breaks
    # the panel's own painting (see lessons/avoid-textual-underscore-collisions).
    def _build(self, result: gitinfo.WorkspaceDiff) -> tuple[Content, list[Widget]]:
        """Return (summary header, per-file collapsible cards)."""
        if result.state is gitinfo.GitState.NO_GIT:
            return (
                Content.from_markup(
                    "[yellow]Git is not installed.[/]\n\n"
                    "[dim]Install git and reopen this panel to see "
                    "working-tree changes.[/]"
                ),
                [],
            )
        if result.state is gitinfo.GitState.NO_REPO:
            return (
                Content.from_markup(
                    "[yellow]Not a git repository.[/]\n\n"
                    "[dim]This folder isn't inside a git work tree.[/]"
                ),
                [],
            )

        files = result.files
        cards = [self._file_card(f) for f in files]
        if result.error:
            # Escape stderr before it hits the markup parser: a literal "[" in a
            # git error would otherwise be read as markup (or raise MarkupError),
            # defeating this panel's never-error promise. _title() escapes too.
            cards.append(
                Static(Text.from_markup(f"[red]git: {_escape(result.error)}[/]"))
            )

        if not files:
            note = "" if not result.error else "\n"
            return (
                Content.from_markup(
                    f"[green]✓ Working tree clean[/] — no uncommitted changes.{note}"
                ),
                cards,
            )

        added = sum(f.added for f in files if not f.is_untracked)
        removed = sum(f.removed for f in files if not f.is_untracked)
        n = len(files)
        parts = [f"[bold]{n} file{'s' if n != 1 else ''} changed[/]"]
        if added:
            parts.append(f"[green]+{added}[/]")
        if removed:
            parts.append(f"[red]−{removed}[/]")
        return Content.from_markup("  ".join(parts)), cards

    @classmethod
    def _file_card(cls, f: gitinfo.FileDiff) -> Collapsible:
        """A collapsible card for one changed file."""
        return Collapsible(
            cls._file_body(f),
            title=cls._title(f),
            collapsed=True,
            classes="diff-file",
        )

    @staticmethod
    def _title(f: gitinfo.FileDiff) -> Content:
        glyph, colour = _STATUS_BADGE.get(f.status, ("◆", "yellow"))
        if f.is_untracked:
            count = f"[dim]· {f.added} lines[/]" if f.added else "[dim]· new[/]"
        else:
            bits = []
            if f.added:
                bits.append(f"[green]+{f.added}[/]")
            if f.removed:
                bits.append(f"[red]−{f.removed}[/]")
            count = " ".join(bits)
        return Content.from_markup(
            f"[{colour}]{glyph}[/] {_escape(f.path)}  {count}".rstrip()
        )

    @staticmethod
    def _file_body(f: gitinfo.FileDiff) -> Static:
        if not f.body.strip():
            return Static(Text("(no preview)", style="dim italic"),
                          classes="diff-file-body")
        try:
            renderable = Syntax(
                f.body,
                f.lexer,
                theme="ansi_dark",
                word_wrap=False,
                background_color="default",
            )
        except ClassNotFound:
            # Unknown lexer for an untracked preview — fall back to plain text.
            renderable = Syntax(
                f.body, "text", theme="ansi_dark",
                word_wrap=False, background_color="default",
            )
        return Static(renderable, classes="diff-file-body")


def _escape(text: str) -> str:
    """Escape Content markup so paths with brackets render literally."""
    return text.replace("\\", "\\\\").replace("[", "\\[")
