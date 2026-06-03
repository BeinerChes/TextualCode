"""WorkspaceController: orchestrates the Review and Commit actions.

These are the two action-bar buttons on the workspace panel. Both follow the
harvester's shape — compute the working-tree diff off the UI thread, run a
throwaway isolated model client, then surface the result — so ``app.py`` carries
only the thin ``@work`` shims and the panel only posts request messages.

- **Review** runs a code-review subagent on the *current* model (read-only tools
  + web search), then injects its findings into the MAIN agent's context as a
  framed prompt — "here's what a reviewer found; tell me what you'd address, but
  don't edit anything yet". The user sees the report and the agent responds.
- **Commit** drafts a message with Haiku, stages everything, and commits
  immediately (no confirmation), then refreshes the diff panel.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from . import gitinfo
from .committer import Committer
from .errors import report_error
from .reviewer import Reviewer

if TYPE_CHECKING:
    from .app import TextualCodeApp

# Framing for the review hand-off to the main agent. The "{review}" slot holds
# the subagent's markdown report. Phrased so the agent summarises and waits —
# no file edits until the user explicitly asks (the chosen "inject as context,
# no auto-edit" behaviour).
_REVIEW_HANDOFF = """\
A code-review subagent examined the current uncommitted working-tree diff and \
produced the findings below. Read them and tell me, concisely, which you agree \
with and how you'd address each — but do **not** modify any files yet; wait \
until I explicitly ask.

---

{review}"""


class WorkspaceController:
    """Orchestrates the workspace panel's Review and Commit actions."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app

    # ----------------------------------------------------------- review --
    async def review(self) -> None:
        """Run the review subagent and inject its report into the main agent."""
        app = self._app
        if not app._agent.connected:
            await app._conversation.add_markdown(
                "> Agent not connected yet — try again in a moment."
            )
            return
        # The hand-off below submits to the main agent (an exclusive AGENT-group
        # worker); firing it mid-turn would silently cancel the live turn and
        # reset the accountant. Refuse instead and tell the user why.
        if app._agent_turn_active:
            await app._conversation.add_markdown(
                "> A turn is already running — interrupt it (Esc) or wait for it "
                "to finish, then press Review again."
            )
            return

        result = await asyncio.to_thread(gitinfo.workspace_diff, app._project_dir)
        note = self._unavailable_note(result.state)
        if note is not None:
            await app._conversation.add_markdown(note)
            return

        diff_text = gitinfo.render_diff_text(result)
        if not diff_text:
            await app._conversation.add_markdown(
                "> ✓ Working tree clean — nothing to review."
            )
            return

        # One source of truth for the model: display exactly what the Reviewer
        # runs with (its CLI value, or a friendly fallback when that is "let the
        # CLI pick"), so the banner can't announce a different model than is used.
        model_id = app._agent.model
        model = model_id or app._model_label or "default"
        await app._conversation.add_markdown(
            f"> 🔍 Reviewing the working-tree diff with **{model}** "
            "(reading the code + web-searching best practices)…"
        )
        # Cold-starting an isolated client + tool use + web search is slow with
        # no streamed output here; animate so it doesn't look frozen.
        app._thinking.start(label="Reviewing", key="review")
        try:
            review = await Reviewer(model=model_id, cwd=app._project_dir).run(
                diff_text
            )
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            app._thinking.stop(key="review")
            await report_error(app._conversation, "Review failed:", exc)
            return
        app._thinking.stop(key="review")

        if not review.text:
            await app._conversation.add_markdown(
                "> The reviewer returned no findings."
            )
            return

        cost = f" · ${review.cost:.4f}" if review.cost is not None else ""
        await app._conversation.add_markdown(
            f"> ✅ Review complete{cost} — handing the findings to the agent."
        )
        # Inject as context: submit the framed report to the main agent. This
        # renders as the turn's user message AND puts the findings in the
        # session context so the agent can reason about them.
        prompt = _REVIEW_HANDOFF.format(review=review.text)
        await app._conversation.add_message("user", prompt)
        app._transcript.add_user(prompt)
        app.send_to_agent(prompt)

    # ----------------------------------------------------------- commit --
    async def commit(self) -> None:
        """Draft a commit message with Haiku, stage all, and commit."""
        app = self._app
        result = await asyncio.to_thread(gitinfo.workspace_diff, app._project_dir)
        note = self._unavailable_note(result.state)
        if note is not None:
            await app._conversation.add_markdown(note)
            return

        diff_text = gitinfo.render_diff_text(result)
        if not diff_text:
            await app._conversation.add_markdown(
                "> ✓ Working tree clean — nothing to commit."
            )
            return

        await app._conversation.add_markdown(
            "> ✍️ Drafting a commit message with Haiku…"
        )
        app._thinking.start(label="Committing", key="commit")
        try:
            drafted = await Committer().run(diff_text)
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
            app._thinking.stop(key="commit")
            await report_error(app._conversation, "Commit message failed:", exc)
            return

        message = drafted.text.strip()
        if not message:
            app._thinking.stop(key="commit")
            await app._conversation.add_markdown(
                "> Couldn't draft a commit message — nothing committed."
            )
            return

        # Stage exactly the reviewed snapshot — not a blanket `git add -A`, which
        # would also commit untracked/unrelated files (e.g. secrets) and anything
        # created since the snapshot, none of which the drafted message describes.
        paths = gitinfo.staged_pathspecs(result)
        commit = await asyncio.to_thread(
            gitinfo.commit_all, app._project_dir, message, paths
        )
        app._thinking.stop(key="commit")

        if commit.nothing_to_commit:
            await app._conversation.add_markdown(
                "> Nothing to commit — working tree already clean."
            )
            return
        if not commit.ok:
            await app._conversation.add_markdown(
                f"> ❌ Commit failed: {commit.error or 'unknown git error'}"
            )
            return

        cost = f" · ${drafted.cost:.4f}" if drafted.cost is not None else ""
        subject = message.splitlines()[0]
        # Surface the SHA + an undo hint: the commit is unconfirmed by design, so
        # make it trivially reversible if the message or scope is wrong.
        sha = f" `{commit.sha}`" if commit.sha else ""
        undo = (
            "\n\n> Undo with `git reset --soft HEAD~1` (keeps your changes staged)."
        )
        await app._conversation.add_markdown(
            f"> ✅ Committed{sha}{cost}:\n\n```\n{message}\n```{undo}"
        )
        app.notify(f"Committed: {subject}", title="Workspace")
        # The tree changed — refresh the diff panel so it reflects the commit.
        app._workspace.refresh_diff()

    # ------------------------------------------------------------ shared --
    @staticmethod
    def _unavailable_note(state: gitinfo.GitState) -> str | None:
        """A friendly markdown note for the non-OK git states, else None."""
        if state is gitinfo.GitState.NO_GIT:
            return "> Git is not installed — install git to use this."
        if state is gitinfo.GitState.NO_REPO:
            return "> Not a git repository — this folder isn't a git work tree."
        return None
