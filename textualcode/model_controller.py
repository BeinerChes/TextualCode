"""ModelController — owns the model-switching feature.

Holds the _models cache and all non-worker model logic. The @work workers
stay on the App (they need MessagePump / push_screen_wait); they delegate
here via ModelController.apply().
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Generator

from textual.app import SystemCommand

from .config import match_model

if TYPE_CHECKING:
    from .app import TextualCodeApp


class ModelController:
    """Owns the model cache and model-switching logic for TextualCodeApp."""

    def __init__(self, app: "TextualCodeApp") -> None:
        self._app = app
        self._models: list[dict] = []

    # ---------------------------------------------------------------- state --

    @property
    def models(self) -> list[dict]:
        return self._models

    def refresh_models(self) -> None:
        """Populate the models cache from the connected agent."""
        self._models = self._app._agent.available_models()

    # --------------------------------------------------------------- actions --

    async def apply(self, name: str) -> None:
        """Switch the active model.

        Verbatim extraction from app.switch_model — every user-visible string
        and code path is preserved byte-for-byte.
        """
        if not self._app._agent.connected:
            await self._app._conversation.add_markdown(
                "> Agent not connected yet — try again in a moment."
            )
            return
        if not name:
            self._app.open_model_selector()  # no arg → open the RadioSet picker
            return

        models = self._app._agent.available_models()
        value = match_model(name, models)
        try:
            await self._app._agent.set_model(value)
        except Exception as exc:  # noqa: BLE001 - report bad ids cleanly
            from .errors import report_error
            await report_error(
                self._app._conversation, None, exc,
                message=f"> **Could not switch model:** {exc}",
            )
            return

        self._app._model_label = value
        self._app._project.model = value
        self._app._project.save(self._app._project_dir)
        self._app._status.set_phase()
        self._app._stats_view.render()
        display = next(
            (m.get("displayName") for m in models if str(m.get("value")) == value), value
        )
        await self._app._conversation.add_markdown(
            f"> Model → **{display}** (`{value}`) · saved."
        )

    # -------------------------------------------------------- palette entries --

    def system_commands(self) -> Generator[SystemCommand, None, None]:
        """Yield model-related command-palette entries."""
        yield SystemCommand(
            "Model: choose…",
            "Pick the agent model",
            self._app.open_model_selector,
        )
        for model in self._models:
            yield SystemCommand(
                f"Model: {model.get('displayName', model['value'])}",
                str(model.get("description", "")),
                partial(self._app._switch_model_worker, str(model["value"])),
            )
