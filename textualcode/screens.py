"""Modal screens: `PermissionDialog` (approve a tool call) and `ToolSelector`
(choose which built-in tools are enabled)."""

from __future__ import annotations

import json
from collections.abc import Iterable

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, RadioButton, RadioSet, SelectionList, Static
from textual.widgets.selection_list import Selection

from .permissions import Decision


class _ChoiceRow(Static):
    """One wrapping option row inside a `ChoiceList`."""

    def __init__(self, index: int, markup: str) -> None:
        super().__init__(markup, classes="choice-row")
        self.index = index

    def on_click(self) -> None:
        # Bubble the index up; the owning ChoiceList focuses + selects.
        self.post_message(ChoiceList.RowClicked(self.index))


class ChoiceList(Vertical, can_focus=True):
    """Keyboard/mouse selectable list whose option text WRAPS.

    Replaces `RadioSet`/`SelectionList` for long option text. Those Textual
    widgets are single-line by design: `RadioButton` hardcodes a content height
    of 1 and keeps only the label's first line, and `OptionList`'s `wrap`
    parameter became a no-op in Textual 1.0 (wrapped text also corrupts its
    indexing — upstream issue #5326). Each row here is a `Static`, which wraps
    when its width is constrained. Verified against installed Textual 8.2.7.

    Single-select mimics a radio group (at most one selection); multi-select
    toggles each row independently like a checkbox list.
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("space,enter", "toggle", "Toggle", show=False),
    ]

    class Changed(Message):
        """Posted when the selection changes."""

        def __init__(self, choice_list: "ChoiceList") -> None:
            super().__init__()
            self.choice_list = choice_list

    class RowClicked(Message):
        """Internal: a row was clicked (carries its index)."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(
        self,
        options: list[dict],
        *,
        multiple: bool,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._options = options
        self._multiple = multiple
        self._highlight = 0 if options else -1
        self._selected: set[int] = set()

    def compose(self) -> ComposeResult:
        for index in range(len(self._options)):
            yield _ChoiceRow(index, self._row_markup(index))

    def on_mount(self) -> None:
        self._sync()

    # --- rendering -------------------------------------------------------
    def _row_markup(self, index: int) -> str:
        option = self._options[index]
        label = escape(str(option.get("label", "")))
        desc = escape(str(option.get("description", "")))
        selected = index in self._selected
        if self._multiple:
            marker = "\\[[b]x[/b]]" if selected else "\\[ ]"
        else:
            marker = "(•)" if selected else "( )"
        head = f"{marker} [b]{label}[/b]" if label else marker
        return f"{head} — {desc}" if desc else head

    def _sync(self) -> None:
        for index, row in enumerate(self.query(_ChoiceRow)):
            row.update(self._row_markup(index))
            row.set_class(index == self._highlight, "-highlight")

    # --- interaction -----------------------------------------------------
    def action_cursor_up(self) -> None:
        if not self._options:
            return
        self._highlight = (self._highlight - 1) % len(self._options)
        self._sync()
        self._scroll_to_highlight()

    def action_cursor_down(self) -> None:
        if not self._options:
            return
        self._highlight = (self._highlight + 1) % len(self._options)
        self._sync()
        self._scroll_to_highlight()

    def action_toggle(self) -> None:
        if self._highlight < 0:
            return
        if self._multiple:
            if self._highlight in self._selected:
                self._selected.discard(self._highlight)
            else:
                self._selected.add(self._highlight)
        else:
            self._selected = {self._highlight}
        self._sync()
        self.post_message(self.Changed(self))

    def on_choice_list_row_clicked(self, event: "ChoiceList.RowClicked") -> None:
        event.stop()
        self.focus()
        self._highlight = event.index
        self.action_toggle()

    def _scroll_to_highlight(self) -> None:
        rows = list(self.query(_ChoiceRow))
        if 0 <= self._highlight < len(rows):
            rows[self._highlight].scroll_visible()

    # --- state for the form ---------------------------------------------
    def selected_labels(self) -> list[str]:
        return [
            str(self._options[i].get("label", "")) for i in sorted(self._selected)
        ]


class PermissionDialog(ModalScreen[Decision]):
    """Approve a tool call: once, similar (remember), or deny."""

    BINDINGS = [
        ("a", "approve_once", "Approve once"),
        ("s", "approve_similar", "Approve similar"),
        ("d", "deny", "Deny"),
        ("escape", "deny", "Deny"),
    ]

    def __init__(self, tool_name: str, tool_input: dict, similar_label: str) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._tool_input = tool_input
        self._similar_label = similar_label

    def compose(self) -> ComposeResult:
        try:
            body = json.dumps(self._tool_input, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            body = str(self._tool_input)
        with Vertical(id="dialog"):
            yield Static(f"🔐 Allow [b]{self._tool_name}[/b] to run?", id="dlg-title")
            yield Static(body, id="dlg-body", markup=False)
            yield Static(
                f'[dim]“Approve similar” allows {self._similar_label} this session.[/dim]',
                id="dlg-hint",
            )
            with Horizontal(id="dlg-buttons"):
                yield Button("Approve once (a)", variant="success", id="once")
                yield Button("Approve similar (s)", variant="warning", id="similar")
                yield Button("Deny (d)", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        decisions = {
            "once": Decision(allow=True, remember=False),
            "similar": Decision(allow=True, remember=True),
            "deny": Decision(allow=False),
        }
        self.dismiss(decisions[event.button.id])

    def action_approve_once(self) -> None:
        self.dismiss(Decision(allow=True, remember=False))

    def action_approve_similar(self) -> None:
        self.dismiss(Decision(allow=True, remember=True))

    def action_deny(self) -> None:
        self.dismiss(Decision(allow=False))


class ConfirmDialog(ModalScreen[bool]):
    """A generic yes/no confirmation. Dismisses with True (confirm) / False."""

    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("escape", "cancel", "No"),
    ]

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_label: str = "Yes (y)",
        cancel_label: str = "No (n)",
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dlg-title")
            yield Static(self._message, id="dlg-body")
            with Horizontal(id="dlg-buttons"):
                yield Button(self._confirm_label, variant="success", id="confirm")
                yield Button(self._cancel_label, variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ToolSelector(ModalScreen[list[str] | None]):
    """Pick which built-in tools are enabled. Dismisses with the selected list,
    or None if cancelled."""

    BINDINGS = [
        ("s", "save", "Save"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, all_tools: Iterable[str], enabled: Iterable[str]) -> None:
        super().__init__()
        self._all_tools = list(all_tools)
        self._enabled = set(enabled)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                "🧰 [b]System tools[/b] — Space toggles · Save (s) applies",
                id="dlg-title",
            )
            yield SelectionList[str](
                *[
                    Selection(name, name, name in self._enabled)
                    for name in self._all_tools
                ],
                id="tool-list",
                compact=bool(getattr(self.app, "compact", False)),
            )
            with Horizontal(id="dlg-buttons"):
                yield Button("Save (s)", variant="success", id="save")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(list(self.query_one(SelectionList).selected))

    def action_cancel(self) -> None:
        self.dismiss(None)


class McpSelector(ModalScreen[list[str] | None]):
    """Pick which MCP servers are enabled. Dismisses with the enabled name list,
    or None if cancelled."""

    BINDINGS = [
        ("s", "save", "Save"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, servers: list[dict]) -> None:
        super().__init__()
        self._servers = servers

    @staticmethod
    def _label(server: dict) -> str:
        """`name (status · scope · N tools)` — purely informational suffix."""
        name = escape(str(server.get("name", "")))
        bits: list[str] = []
        status = str(server.get("status", "")).strip()
        scope = str(server.get("scope", "")).strip()
        tools = server.get("tools")
        if status:
            bits.append(status)
        if scope:
            bits.append(scope)
        if isinstance(tools, list) and tools:
            bits.append(f"{len(tools)} tools")
        return f"{name} ({escape(' · '.join(bits))})" if bits else name

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                "🔌 [b]MCP servers[/b] — Space toggles · Save (s) applies",
                id="dlg-title",
            )
            if not self._servers:
                yield Static(
                    "[dim]No MCP servers found in this project's `.mcp.json` or "
                    "your user settings.[/dim]",
                    id="dlg-body",
                )
            else:
                yield SelectionList[str](
                    *[
                        Selection(
                            self._label(server),
                            str(server.get("name", "")),
                            # Initial check state from LIVE status, not a cached
                            # wishlist — a server reporting "disabled" is off.
                            server.get("status") != "disabled",
                        )
                        for server in self._servers
                    ],
                    id="mcp-list",
                    compact=bool(getattr(self.app, "compact", False)),
                )
            with Horizontal(id="dlg-buttons"):
                yield Button("Save (s)", variant="success", id="save")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        if not self._servers:
            self.dismiss([])  # nothing to choose — treat as a no-op save
            return
        self.dismiss(list(self.query_one(SelectionList).selected))

    def action_cancel(self) -> None:
        self.dismiss(None)


class QuestionForm(ModalScreen[dict | None]):
    """Render an `AskUserQuestion` tool call as an interactive form.

    Dismisses with {question_text: label | [labels]} or None if cancelled.
    """

    BINDINGS = [
        ("ctrl+s", "submit", "Submit"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, questions: list[dict]) -> None:
        super().__init__()
        self._questions = questions

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                "❓ [b]Claude has a question[/b] — Submit (Ctrl+S) · Esc cancels",
                id="dlg-title",
            )
            with VerticalScroll(id="question-scroll"):
                for index, q in enumerate(self._questions):
                    header = q.get("header", "")
                    text = q.get("question", "")
                    yield Static(f"[b]{header}[/b]  {text}".strip(), classes="q-text")
                    yield ChoiceList(
                        q.get("options", []),
                        multiple=bool(q.get("multiSelect")),
                        id=f"q-{index}",
                        classes="q-choices",
                    )
            with Horizontal(id="dlg-buttons"):
                yield Button("Submit (Ctrl+S)", variant="success", id="submit")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        # Nothing is selected yet, so Submit starts disabled (see _all_answered).
        self._refresh_submit_enabled()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.dismiss(None)

    # A selection in any question may complete (or un-complete) the form, so
    # re-evaluate the Submit button's enabled state on every change.
    def on_choice_list_changed(self, event: ChoiceList.Changed) -> None:
        self._refresh_submit_enabled()

    def _all_answered(self) -> bool:
        """True only when every question has at least one selection."""
        for index in range(len(self._questions)):
            widget = self.query_one(f"#q-{index}", ChoiceList)
            if not widget.selected_labels():
                return False
        return True

    def _refresh_submit_enabled(self) -> None:
        self.query_one("#submit", Button).disabled = not self._all_answered()

    def action_submit(self) -> None:
        # Keyboard backstop: the Submit button is disabled while incomplete, but
        # the ctrl+s binding routes here directly, so guard the empty case too.
        if not self._all_answered():
            self.app.bell()
            return
        answers: dict = {}
        for index, q in enumerate(self._questions):
            qtext = q.get("question", "")
            widget = self.query_one(f"#q-{index}", ChoiceList)
            labels = widget.selected_labels()
            if q.get("multiSelect"):
                answers[qtext] = labels
            else:
                answers[qtext] = labels[0] if labels else ""
        self.dismiss(answers)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ModelSelector(ModalScreen[str | None]):
    """Pick the agent model from a radio list. Dismisses with the chosen
    `value`, or None if cancelled."""

    BINDINGS = [
        ("s", "save", "Select"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, models: list[dict], current: str | None) -> None:
        super().__init__()
        self._models = models
        self._current = str(current)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("🧠 [b]Choose model[/b] — Select (s) · Esc cancels", id="dlg-title")
            with RadioSet(id="model-set", compact=bool(getattr(self.app, "compact", False))):
                for model in self._models:
                    name = model.get("displayName", model["value"])
                    desc = model.get("description", "")
                    yield RadioButton(
                        f"{name} — {desc}" if desc else str(name),
                        value=str(model["value"]) == self._current,
                    )
            with Horizontal(id="dlg-buttons"):
                yield Button("Select (s)", variant="success", id="select")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select":
            self.action_save()
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        index = self.query_one(RadioSet).pressed_index
        if index < 0:
            self.dismiss(None)
            return
        self.dismiss(str(self._models[index]["value"]))

    def action_cancel(self) -> None:
        self.dismiss(None)


class EffortSelector(ModalScreen[str | None]):
    """Pick the agent reasoning effort from a radio list. Dismisses with the
    chosen `value` (an EFFORT_VALUES string), or None if cancelled."""

    BINDINGS = [
        ("s", "save", "Select"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, levels: list[dict], current: str | None) -> None:
        super().__init__()
        self._levels = levels
        self._current = str(current)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                "🎚️ [b]Choose effort[/b] — Select (s) · Esc cancels", id="dlg-title"
            )
            with RadioSet(id="effort-set", compact=bool(getattr(self.app, "compact", False))):
                for level in self._levels:
                    label = level.get("label", level["value"])
                    desc = level.get("description", "")
                    yield RadioButton(
                        f"{label} — {desc}" if desc else str(label),
                        value=str(level["value"]) == self._current,
                    )
            with Horizontal(id="dlg-buttons"):
                yield Button("Select (s)", variant="success", id="select")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select":
            self.action_save()
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        index = self.query_one(RadioSet).pressed_index
        if index < 0:
            self.dismiss(None)
            return
        self.dismiss(str(self._levels[index]["value"]))

    def action_cancel(self) -> None:
        self.dismiss(None)
