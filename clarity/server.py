from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .media import doctor, frame, inspect_video, probe
from .models import Cue, Project, subtitle_text
from .output import browser_preview, export, export_audio, narrate, narration_status, render
from .settings import EditorPreferences, PreferencePatch, editor_preferences as read_editor_preferences, update_editor_preferences
from .speech import Provider, SpeechPreferences, SpeechService, SpeechSettings
from .store import ROOT, ConflictError, Store


class ImportRequest(BaseModel):
    path: str
    title: str | None = None


class CueRequest(BaseModel):
    revision: int = Field(ge=0)
    cues: list[Cue]
    title: str | None = None


class InspectionRequest(BaseModel):
    every: float = Field(default=5, ge=0.1, allow_inf_nan=False)
    max_frames: int = Field(default=48, ge=1, le=120)


class NarrationRequest(BaseModel):
    provider: Provider | None = None
    voice: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=256)
    instructions: str | None = Field(default=None, max_length=2000)
    cue_ids: list[str] | None = Field(default=None, max_length=1000)


class ConnectionRequest(BaseModel):
    settings: SpeechSettings | None = None
    credential_provider: Provider | None = None
    api_key: SecretStr | None = None
    remember_key: bool = False
    clear_key: bool = False


class DiscoverRequest(BaseModel):
    provider: Provider = "openrouter"
    base_url: str | None = None
    model: str | None = None


class SpeechChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider
    preferences: SpeechPreferences


def create_app(store: Store | None = None, speech: SpeechService | None = None) -> FastAPI:
    store = store or Store()
    speech = speech or SpeechService(store)
    app = FastAPI(title="Clarity Studio", version="0.1.0", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clarity")
    jobs = {}
    busy = set()
    lock = threading.Lock()

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host')}"
        if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Only requests from this local app are accepted."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ConflictError)
    async def conflict_handler(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(FileNotFoundError)
    async def missing_handler(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def value_handler(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request, error):
        # FastAPI's default error includes input values, which may contain keys.
        errors = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    def present(project: Project) -> dict:
        return {**project.model_dump(), "warnings": project.warnings(), "narration": narration_status(store, project), "preview_available": (store.directory(project.id) / "preview.mp4").is_file()}

    def queue(project_id: str, function) -> dict:
        store.get(project_id)
        job_id = uuid.uuid4().hex
        with lock:
            if project_id in busy:
                raise ConflictError("This recording already has a task running. Wait for it to finish.")
            busy.add(project_id)
            if len(jobs) > 100:
                for key in list(jobs):
                    if jobs[key]["status"] in ("done", "error"):
                        del jobs[key]
                        if len(jobs) <= 50:
                            break
            jobs[job_id] = {"id": job_id, "project_id": project_id, "status": "running", "message": "Starting…"}

        def progress(message):
            with lock:
                jobs[job_id]["message"] = message

        def work():
            try:
                result = function(progress)
                with lock:
                    jobs[job_id].update(status="done", message="Finished", result=result)
            except Exception as error:
                with lock:
                    jobs[job_id].update(status="error", message=str(error))
            finally:
                with lock:
                    busy.discard(project_id)

        executor.submit(work)
        return {"job_id": job_id}

    @app.get("/api/health")
    def health():
        return {"app": "clarity-studio", "version": "0.1.0", "workspace": str(ROOT), "projects_directory": str(store.root), "narration_configured": speech.public_settings()["keys"]["openrouter"]["configured"], "default_voice": os.environ.get("OPENROUTER_VOICE", "")}

    @app.get("/api/preferences")
    def editor_preferences():
        return read_editor_preferences(speech)

    @app.put("/api/preferences")
    def save_editor_preferences(body: PreferencePatch):
        return update_editor_preferences(speech, body.model_dump(exclude_unset=True))

    @app.get("/api/speech/settings")
    def speech_settings():
        return speech.public_settings()

    @app.put("/api/speech/settings")
    def save_speech_settings(body: ConnectionRequest):
        if body.settings is None:
            # Credential-only clients must not copy old settings back over a
            # concurrent editor/CLI change just to update a session or key.
            if body.credential_provider is None:
                raise HTTPException(status_code=422, detail="Provide settings or an explicit credential provider for a key-only request.")
            if body.clear_key:
                return speech.clear_key(body.credential_provider)
            if body.api_key is not None:
                return speech.set_key(body.credential_provider, body.api_key.get_secret_value(), body.remember_key)
            if body.remember_key:
                return speech.remember_key(body.credential_provider)
            raise ValueError("Provide a key, choose Keychain storage, or request key removal.")
        return speech.save(body.settings, body.api_key.get_secret_value() if body.api_key else None, body.remember_key, body.clear_key, body.credential_provider)

    @app.patch("/api/speech/preferences")
    def save_speech_choices(body: SpeechChoiceRequest):
        return speech.save_choices(body.provider, body.preferences)

    @app.post("/api/speech/discover")
    def discover_speech(body: DiscoverRequest):
        return speech.discover(body.provider, body.base_url, body.model)

    @app.post("/api/speech/test")
    def test_speech(body: DiscoverRequest):
        return speech.test_connection(body.provider)

    @app.get("/api/doctor")
    def dependencies():
        return doctor()

    @app.get("/api/projects")
    def projects():
        return [{"id": p.id, "title": p.title, "duration": p.video.duration, "cue_count": len(p.cues), "revision": p.revision} for p in store.list()]

    @app.post("/api/projects", status_code=201)
    def import_video(body: ImportRequest):
        return present(store.create(probe(Path(body.path)), body.title))

    @app.post("/api/upload", status_code=201)
    def upload(file: UploadFile):
        name = Path(file.filename or "recording.mp4").name
        suffix = Path(name).suffix.lower()
        if suffix not in (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"):
            raise ValueError("Choose an MP4, MOV, M4V, WebM, MKV, or AVI video.")
        directory = store.root / "_uploads" / uuid.uuid4().hex
        directory.mkdir(parents=True)
        target = directory / name
        try:
            with target.open("wb") as output:
                size = 0
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 10 * 1024 ** 3:
                        raise ValueError("This recording exceeds the 10 GB upload limit. Import it by local path instead.")
                    output.write(chunk)
            return present(store.create(probe(target), Path(name).stem))
        except Exception:
            target.unlink(missing_ok=True)
            directory.rmdir()
            raise
        finally:
            file.file.close()

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        return present(store.get(project_id))

    @app.put("/api/projects/{project_id}/cues")
    def save_cues(project_id: str, body: CueRequest):
        return present(store.update(project_id, body.cues, body.revision, body.title))

    @app.get("/api/projects/{project_id}/media")
    def media(project_id: str):
        path = Path(store.get(project_id).video.path)
        if not path.is_file():
            raise FileNotFoundError("The original video has moved. Import it again from its new location.")
        return FileResponse(path)

    @app.get("/api/projects/{project_id}/frame")
    def get_frame(project_id: str, time: float = 0, width: int = 1600):
        return FileResponse(frame(store, store.get(project_id), time, width), media_type="image/jpeg")

    @app.get("/api/projects/{project_id}/subtitles.vtt")
    def vtt(project_id: str):
        return PlainTextResponse(subtitle_text(store.get(project_id), "vtt"), media_type="text/vtt")

    @app.get("/api/projects/{project_id}/export/{format}")
    def export_captions(project_id: str, format: str):
        output = export(store, store.get(project_id), format)
        return FileResponse(output, filename=output.name)

    @app.get("/api/projects/{project_id}/files/{relative:path}")
    def get_asset(project_id: str, relative: str, download: bool = False):
        path = store.asset(project_id, relative)
        return FileResponse(path, filename=path.name if download else None)

    @app.post("/api/projects/{project_id}/inspect")
    def prepare(project_id: str, body: InspectionRequest):
        project = store.get(project_id)
        return queue(project_id, lambda progress: inspect_video(store, project, body.every, body.max_frames, progress))

    @app.post("/api/projects/{project_id}/render")
    def render_video(project_id: str, narrated: bool = False):
        project = store.get(project_id)

        def perform(progress):
            output = render(store, project, narrated, progress)
            return {"path": str(output), "file": str(output.relative_to(store.directory(project_id)))}

        return queue(project_id, perform)

    @app.post("/api/projects/{project_id}/narrate")
    def voice(project_id: str, body: NarrationRequest):
        project = store.get(project_id)
        connection, model, voice, instructions = speech.resolve(body.provider, body.model, body.voice, body.instructions)
        return queue(project_id, lambda progress: narrate(store, project, voice, model, instructions, progress, connection=connection, cue_ids=body.cue_ids))

    @app.post("/api/projects/{project_id}/audio")
    def audio(project_id: str, format: str = "mp3"):
        project = store.get(project_id)

        def perform(progress):
            progress("Exporting the timed narration track…")
            output = export_audio(store, project, format)
            return {"path": str(output), "file": str(output.relative_to(store.directory(project_id)))}

        return queue(project_id, perform)

    @app.post("/api/projects/{project_id}/preview")
    def preview(project_id: str):
        project = store.get(project_id)

        def perform(progress):
            output = browser_preview(store, project, progress)
            return {"path": str(output), "file": "preview.mp4"}

        return queue(project_id, perform)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        with lock:
            if job_id not in jobs:
                raise HTTPException(404, "Task not found. The app may have restarted; saved files remain in the project folder.")
            return dict(jobs[job_id])

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app
