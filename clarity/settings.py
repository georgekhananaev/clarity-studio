"""Validated editor settings shared by the browser API and headless CLI."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from .speech import SpeechService


class EditorPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appearance: Literal["light", "dark", "system"] = "dark"
    playback_speed: Literal[0.5, 0.75, 1, 1.5, 2] = 1
    muted: bool = False
    caption_size: Literal[18, 22, 28] = 22
    sidebar_collapsed: bool = False
    sidebar_width: int = Field(default=216, ge=168, le=360, strict=True)
    preview_share: float = Field(default=0.66, ge=0.5, le=0.75, allow_inf_nan=False)
    preferences_pane: Literal["general", "integrations"] = "general"
    last_project: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")


class PreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appearance: Literal["light", "dark", "system"] | None = None
    playback_speed: Literal[0.5, 0.75, 1, 1.5, 2] | None = None
    muted: bool | None = None
    caption_size: Literal[18, 22, 28] | None = None
    sidebar_collapsed: bool | None = None
    sidebar_width: int | None = Field(default=None, ge=168, le=360, strict=True)
    preview_share: float | None = Field(default=None, ge=0.5, le=0.75, allow_inf_nan=False)
    preferences_pane: Literal["general", "integrations"] | None = None
    last_project: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")


def _validated_editor_preferences(values: dict) -> dict:
    try:
        return EditorPreferences.model_validate(values).model_dump()
    except ValidationError:
        raise ValueError("Invalid editor preferences. Check the supported fields and allowed values.") from None


def editor_preferences(speech: SpeechService) -> dict:
    values = _validated_editor_preferences(speech.config.get("editor", {}))
    return {**values, "storage": {"database": str(speech.config.path), "projects": str(speech.store.root), "credentials": "macOS Keychain"}}


def update_editor_preferences(speech: SpeechService, patch: dict) -> dict:
    try:
        accepted = PreferencePatch.model_validate(patch).model_dump(exclude_unset=True)
    except ValidationError:
        raise ValueError("Invalid editor preferences. Check the supported fields and allowed values.") from None
    # A null last_project explicitly clears the remembered recording. Other
    # null fields retain the API's existing no-change semantics.
    accepted = {key: value for key, value in accepted.items() if value is not None or key == "last_project"}
    speech.config.update("editor", accepted, validate=_validated_editor_preferences)
    return editor_preferences(speech)
