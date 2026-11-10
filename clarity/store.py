from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import Cue, Project, Video, now

ROOT = Path(__file__).resolve().parent.parent


class ConflictError(ValueError):
    pass


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or Path(os.environ.get("CLARITY_PROJECTS_DIR", ROOT / "projects"))).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", project_id):
            raise ValueError("Invalid project ID.")
        root = str(self.root)
        path = os.path.normpath(os.path.join(root, project_id))
        if not path.startswith(root + os.sep):
            raise ValueError("Invalid project ID.")
        return Path(path)

    @contextmanager
    def locked(self, project_id: str):
        directory = self.directory(project_id)
        if not (directory / "project.json").is_file():
            raise FileNotFoundError("Project not found.")
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def get(self, project_id: str) -> Project:
        return Project.model_validate_json((self.directory(project_id) / "project.json").read_text())

    def list(self) -> list[Project]:
        projects = []
        for path in self.root.glob("*/project.json"):
            try:
                projects.append(Project.model_validate_json(path.read_text()))
            except (ValueError, OSError):
                continue
        return sorted(projects, key=lambda p: p.updated_at, reverse=True)

    def create(self, video: Video, title: str | None = None) -> Project:
        title = (title or Path(video.name).stem).strip()[:160]
        if not title:
            raise ValueError("Project title cannot be empty.")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "recording"
        project = Project(id=f"{slug}-{uuid.uuid4().hex[:8]}", title=title, video=video)
        atomic_write(self.directory(project.id) / "project.json", project.model_dump_json(indent=2))
        return project

    def update(self, project_id: str, cues: list[Cue], revision: int, title: str | None = None) -> Project:
        with self.locked(project_id) as directory:
            current = self.get(project_id)
            if current.revision != revision:
                raise ConflictError(f"Project changed: expected revision {revision}, current revision {current.revision}. Reload before saving.")
            values = current.model_dump()
            values.update(cues=[cue.model_dump() for cue in cues], revision=revision + 1, updated_at=now())
            if title is not None:
                title = title.strip()[:160]
                if not title:
                    raise ValueError("Project title cannot be empty.")
                values["title"] = title
            updated = Project.model_validate(values)
            history = directory / "history" / f"{current.revision:06}.json"
            atomic_write(history, current.model_dump_json(indent=2))
            atomic_write(directory / "project.json", updated.model_dump_json(indent=2))
            return updated

    def asset(self, project_id: str, relative: str) -> Path:
        directory = os.path.realpath(self.directory(project_id))
        path = os.path.realpath(os.path.join(directory, relative))
        if not path.startswith(directory + os.sep) or not os.path.isfile(path):
            raise FileNotFoundError("File not found.")
        return Path(path)
