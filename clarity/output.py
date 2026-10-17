from __future__ import annotations

import hashlib
import json
import os
import tempfile
import wave
from pathlib import Path

import httpx

from .media import run
from .models import Cue, Project, subtitle_text
from .store import Store, atomic_write
from .speech import Connection, SpeechService, check_response

SAMPLE_RATE = 48000


def export(store: Store, project: Project, format: str = "srt") -> Path:
    if format not in ("srt", "vtt", "json", "txt"):
        raise ValueError("Export format must be srt, vtt, json, or txt.")
    path = store.directory(project.id) / "exports" / f"captions-r{project.revision}.{format}"
    atomic_write(path, subtitle_text(project, format))
    return path


def text_hash(cue: Cue) -> str:
    return hashlib.sha256(cue.text.encode()).hexdigest()


def narration_manifest(store: Store, project: Project) -> dict:
    path = store.directory(project.id) / "narration" / "manifest.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def narration_status(store: Store, project: Project) -> list[dict]:
    manifest = narration_manifest(store, project)
    rows = []
    for cue in project.cues:
        entry = manifest.get(cue.id)
        row = {"cue_id": cue.id, "status": "missing", "duration": None}
        if entry:
            if entry["text_hash"] != text_hash(cue):
                row["status"] = "stale"
            elif not (store.directory(project.id) / "narration" / entry["file"]).is_file():
                row["status"] = "missing"
            else:
                row.update(duration=entry["duration"], file=entry["file"], model=entry["model"], provider=entry.get("provider", "openrouter"), voice=entry.get("voice", ""))
                row["status"] = "overflow" if entry["duration"] > cue.end - cue.start + 1 / SAMPLE_RATE else "ready"
        rows.append(row)
    return rows


def narrate(store: Store, project: Project, voice: str, model: str = "fish-audio/drama-3", instructions: str = "Speak clearly and naturally, as a concise software tutorial.", progress=None, client=None, connection: Connection | None = None, cue_ids: list[str] | None = None) -> dict:
    connection = connection or SpeechService(store).connection("openrouter")
    if connection.provider == "openrouter" and not connection.key:
        raise ValueError("Add your OpenRouter API key in the narration panel, or set OPENROUTER_API_KEY.")
    if not voice.strip():
        raise ValueError("Enter a voice ID supported by your selected speech model.")
    if not project.cues:
        raise ValueError("Add captions before generating narration.")
    directory = store.directory(project.id) / "narration"
    directory.mkdir(exist_ok=True)
    cues = project.cues
    if cue_ids is not None:
        if not cue_ids or set(cue_ids) - {cue.id for cue in cues}:
            raise ValueError("Choose existing caption IDs for speech generation.")
        cues = [cue for cue in cues if cue.id in cue_ids]
    instructions = instructions if connection.provider == "openrouter" else ""
    context = client or httpx.Client(timeout=httpx.Timeout(180, connect=15), follow_redirects=False, trust_env=False)
    try:
        for index, cue in enumerate(cues):
            if progress:
                progress(f"Generating voice {index + 1} of {len(cues)}")
            signature = hashlib.sha256(json.dumps([connection.provider, connection.base_url, cue.text, voice, model, instructions]).encode()).hexdigest()[:20]
            filename = f"{cue.id}-{signature}.wav"
            output = directory / filename
            if not output.is_file():
                # No automatic retries: a repeated speech request may be billed again.
                try:
                    payload = {"model": model, "input": cue.text, "voice": voice, "response_format": "mp3" if connection.provider == "openrouter" else "wav"}
                    if instructions:
                        payload["instructions"] = instructions
                    response = context.post(connection.base_url + "/audio/speech", headers=connection.headers, json=payload)
                    check_response(response, connection)
                except httpx.HTTPError as error:
                    raise ValueError("The speech request failed. Check the provider connection before retrying.") from error
                if not response.content:
                    raise ValueError("The speech provider returned empty audio.")
                with tempfile.TemporaryDirectory(prefix="speech-", dir=directory) as work:
                    raw = Path(work) / "speech.audio"
                    raw.write_bytes(response.content)
                    converted = Path(work) / "speech.wav"
                    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(converted)])
                    with wave.open(str(converted), "rb") as audio:
                        if not audio.getnframes():
                            raise ValueError("Generated audio has no samples.")
                    os.replace(converted, output)
            with wave.open(str(output), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
            with store.locked(project.id):
                manifest = narration_manifest(store, project)
                manifest[cue.id] = {"file": filename, "text_hash": text_hash(cue), "duration": duration, "model": model, "voice": voice, "instructions": instructions, "provider": connection.provider, "base_url": connection.base_url}
                atomic_write(directory / "manifest.json", json.dumps(manifest, indent=2))
    finally:
        if client is None:
            context.close()
    current = store.get(project.id)
    return {"segments": narration_status(store, current), "note": "Extend a caption's duration or shorten its wording if the generated voice runs too long."}


def narration_track(store: Store, project: Project, output: Path) -> None:
    statuses = narration_status(store, project)
    bad = [row for row in statuses if row["status"] != "ready"]
    if bad or not project.cues:
        raise ValueError("Narration is incomplete, outdated, or too long for a caption. Generate missing audio and fix any timing overflow before exporting.")
    manifest = narration_manifest(store, project)
    with wave.open(str(output), "wb") as target:
        target.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        cursor = 0

        def silence(frames: int):
            while frames > 0:
                amount = min(frames, SAMPLE_RATE)
                target.writeframesraw(b"\0\0" * amount)
                frames -= amount

        for cue in project.cues:
            start = round(cue.start * SAMPLE_RATE)
            silence(max(0, start - cursor))
            cursor = max(cursor, start)
            with wave.open(str(store.directory(project.id) / "narration" / manifest[cue.id]["file"]), "rb") as segment:
                while data := segment.readframes(SAMPLE_RATE):
                    target.writeframesraw(data)
                    cursor += len(data) // 2
        silence(max(0, round(project.video.duration * SAMPLE_RATE) - cursor))


def export_audio(store: Store, project: Project, format: str = "mp3") -> Path:
    if format not in ("mp3", "wav"):
        raise ValueError("Audio export format must be mp3 or wav.")
    directory = store.directory(project.id) / "exports"
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audio-", dir=directory) as work:
        work = Path(work)
        narration_track(store, project, work / "track.wav")
        temporary = work / f"narration.{format}"
        if format == "mp3":
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(work / "track.wav"), "-c:a", "libmp3lame", "-q:a", "2", str(temporary)])
        else:
            temporary = work / "track.wav"
        output = directory / f"narration-r{project.revision}.{format}"
        os.replace(temporary, output)
    return output


def render(store: Store, project: Project, narrated: bool = False, progress=None) -> Path:
    if not project.cues:
        raise ValueError("Add at least one caption before exporting a video.")
    directory = store.directory(project.id) / "exports"
    directory.mkdir(exist_ok=True)
    if progress:
        progress("Rendering captions and video…")
    with tempfile.TemporaryDirectory(prefix="render-", dir=directory) as work:
        work = Path(work)
        (work / "captions.srt").write_text(subtitle_text(project, "srt"), encoding="utf-8")
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", project.video.path]
        if narrated:
            narration_track(store, project, work / "narration.wav")
            command.extend(["-i", str(work / "narration.wav"), "-map", "0:v:0", "-map", "1:a:0"])
        else:
            command.extend(["-map", "0:v:0", "-map", "0:a:0?"])
        command.extend(["-vf", "subtitles=filename=captions.srt:force_style='FontName=Arial,FontSize=19,Outline=1.2,Shadow=0,MarginV=20',pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(project.video.duration), "-movflags", "+faststart", str(work / "output.mp4")])
        run(command, timeout=max(120, min(7200, int(project.video.duration * 12))), cwd=work)
        output = directory / f"{'narrated' if narrated else 'captioned'}-r{project.revision}.mp4"
        os.replace(work / "output.mp4", output)
    return output


def browser_preview(store: Store, project: Project, progress=None) -> Path:
    if progress:
        progress("Creating a browser-compatible preview…")
    directory = store.directory(project.id)
    with tempfile.TemporaryDirectory(prefix="preview-", dir=directory) as work:
        temporary = Path(work) / "preview.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", project.video.path, "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=w='min(1280,iw)':h=-2,pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(temporary)], timeout=max(120, min(7200, int(project.video.duration * 12))))
        os.replace(temporary, directory / "preview.mp4")
    return directory / "preview.mp4"
