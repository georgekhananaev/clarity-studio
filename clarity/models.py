from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Cue(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        value = re.sub(r"\n(?:[\t ]*\n)+", "\n", value)
        if not value or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Caption text must contain readable text without control characters.")
        return value

    @model_validator(mode="after")
    def check_interval(self):
        self.start = round(self.start, 3)
        self.end = round(self.end, 3)
        if self.end <= self.start:
            raise ValueError("Caption end must be after its start (at millisecond precision).")
        return self


class Video(BaseModel):
    path: str
    name: str
    duration: float = Field(gt=0, allow_inf_nan=False)
    width: int
    height: int
    has_audio: bool = False


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    id: str
    title: str
    revision: int = 0
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    video: Video
    cues: list[Cue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cues(self):
        self.cues.sort(key=lambda cue: (cue.start, cue.end))
        seen = set()
        previous = None
        for cue in self.cues:
            if cue.id in seen:
                raise ValueError(f"Duplicate caption ID: {cue.id}")
            seen.add(cue.id)
            if cue.end > self.video.duration + 0.001:
                raise ValueError(f"Caption {cue.id} ends beyond the video ({self.video.duration:.3f}s).")
            if previous and cue.start < previous.end:
                raise ValueError(f"Captions overlap: {previous.id} and {cue.id}.")
            previous = cue
        return self

    def warnings(self) -> list[dict]:
        issues = []
        for cue in self.cues:
            rate = len(cue.text.replace("\n", "")) / (cue.end - cue.start)
            if rate > 22:
                issues.append({"cue_id": cue.id, "message": f"Fast reading speed: {rate:.0f} characters/second."})
            if cue.end - cue.start < 0.7:
                issues.append({"cue_id": cue.id, "message": "On screen for less than 0.7 seconds."})
        return issues


def timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{milliseconds:03}"


def subtitle_text(project: Project, format: str) -> str:
    import html

    if format == "txt":
        return "\n\n".join(cue.text for cue in project.cues) + "\n"
    if format == "json":
        return project.model_dump_json(indent=2) + "\n"
    blocks = []
    for index, cue in enumerate(project.cues, 1):
        separator = "." if format == "vtt" else ","
        text = html.escape(cue.text, quote=False) if format == "vtt" else cue.text
        blocks.append(f"{index}\n{timestamp(cue.start, separator)} --> {timestamp(cue.end, separator)}\n{text}")
    return ("WEBVTT\n\n" if format == "vtt" else "") + "\n\n".join(blocks) + "\n"
