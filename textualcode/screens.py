"""Modal screens: `PermissionDialog` (approve a tool call) and `ToolSelector`
(choose which built-in tools are enabled)."""

from __future__ import annotations

import json
from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, RadioButton, RadioSet, SelectionList, Static
from textual.widgets.selection_list import Selection

from .permissions import Decision


def _option_label(option: dict) -> str:
    label = option.get("label", "")
    desc = option.get("description", "")
    return f"{label} — {desc}" if desc else str(label)


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
                    options = q.get("options", [])
                    if q.get("multiSelect"):
                        yield SelectionList[str](
                            *[
                                Selection(_option_label(o), o.get("label", ""))
                                for o in options
                            ],
                            id=f"q-{index}",
                            classes="q-input",
                        )
                    else:
                        with RadioSet(id=f"q-{index}", classes="q-input"):
                            for o in options:
                                yield RadioButton(_option_label(o))
            with Horizontal(id="dlg-buttons"):
                yield Button("Submit (Ctrl+S)", variant="success", id="submit")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.dismiss(None)

    def action_submit(self) -> None:
        answers: dict = {}
        for index, q in enumerate(self._questions):
            qtext = q.get("question", "")
            options = q.get("options", [])
            widget = self.query_one(f"#q-{index}")
            if q.get("multiSelect"):
                answers[qtext] = list(widget.selected)  # type: ignore[attr-defined]
            else:
                idx = widget.pressed_index  # type: ignore[attr-defined]
                answers[qtext] = options[idx].get("label", "") if 0 <= idx < len(options) else ""
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
            with RadioSet(id="model-set"):
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
