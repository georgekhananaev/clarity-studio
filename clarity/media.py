from __future__ import annotations

import json
import math
import shutil
import subprocess
import os
import tempfile
from pathlib import Path

from .models import Project, Video, timestamp
from .store import Store, atomic_write


def executable(name: str) -> str | None:
    override = os.environ.get(f"CLARITY_{name.upper()}")
    if override:
        return shutil.which(override)
    for prefix in ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"):
        path = Path(prefix) / name
        if path.is_file():
            return str(path)
    return shutil.which(name)


def run(command: list[str], timeout: int = 120, cwd: Path | None = None) -> str:
    if command[0] in ("ffmpeg", "ffprobe"):
        command = [executable(command[0]) or command[0], *command[1:]]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except FileNotFoundError as error:
        raise ValueError(f"{command[0]} is missing. Run ./setup.command first.") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"{command[0]} timed out after {timeout} seconds.") from error
    if result.returncode:
        raise ValueError(f"{command[0]} failed: {result.stderr[-2500:].strip()}")
    return result.stdout


def probe(path: Path) -> Video:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    data = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], 30))
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ValueError("This file does not contain a video stream.")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Cannot determine this video's duration.")
    return Video(path=str(path), name=path.name, duration=duration, width=video["width"], height=video["height"], has_audio=any(s.get("codec_type") == "audio" for s in streams))


def frame(store: Store, project: Project, time: float, width: int = 1600) -> Path:
    if not math.isfinite(time) or time < 0 or time >= project.video.duration:
        raise ValueError("Frame time must be inside the video.")
    if width != 0 and not 320 <= width <= 3840:
        raise ValueError("Frame width must be 320–3840 pixels, or 0 for original resolution.")
    output = store.directory(project.id) / "frames" / f"frame-{round(time * 1000):010}-w{width}.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file():
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(time), "-i", project.video.path, "-frames:v", "1"]
        if width:
            command.extend(["-vf", f"scale=w='min({width},iw)':h=-2"])
        with tempfile.TemporaryDirectory(prefix="frame-", dir=output.parent) as work:
            temporary = Path(work) / "frame.jpg"
            run([*command, "-q:v", "3", str(temporary)], 45)
            if not temporary.is_file():
                raise ValueError("No frame could be decoded at this time. Try slightly earlier.")
            os.replace(temporary, output)
    if not output.is_file():
        raise ValueError("No frame could be decoded at this time. Try slightly earlier.")
    return output


def inspect_video(store: Store, project: Project, every: float = 5, max_frames: int = 48, progress=None) -> dict:
    from PIL import Image, ImageDraw, ImageFont

    if not math.isfinite(every) or every < 0.1 or not 1 <= max_frames <= 120:
        raise ValueError("Use an interval of at least 0.1s and 1–120 frames.")
    count = min(max_frames, max(1, math.ceil(project.video.duration / every)))
    # Cover the whole recording even when the requested interval exceeds the frame limit.
    interval = max(every, project.video.duration / count)
    frames = []
    for index in range(count):
        time = round(index * interval, 3)
        if progress:
            progress(f"Inspecting frame {index + 1} of {count}")
        path = frame(store, project, time, width=960)
        frames.append({"time": time, "label": timestamp(time, "."), "path": str(path)})
    directory = store.directory(project.id) / "inspection"
    directory.mkdir(exist_ok=True)
    sheets = []
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 17)
    except OSError:
        font = ImageFont.load_default(size=17)
    for page in range(0, len(frames), 12):
        batch = frames[page:page + 12]
        rows = math.ceil(len(batch) / 3)
        sheet = Image.new("RGB", (1200, rows * 258), "#10131b")
        draw = ImageDraw.Draw(sheet)
        for index, entry in enumerate(batch):
            x, y = (index % 3) * 400, (index // 3) * 258
            with Image.open(entry["path"]) as original:
                original.thumbnail((384, 216))
                sheet.paste(original, (x + (400 - original.width) // 2, y + (216 - original.height) // 2))
            draw.text((x + 10, y + 226), entry["label"], fill="#c5dcb9", font=font)
        output = directory / f"contact-{page // 12 + 1:02}.jpg"
        sheet.save(output, quality=90)
        sheets.append(str(output))
    manifest = {"project_id": project.id, "revision": project.revision, "duration": project.video.duration, "sample_interval": interval, "frames": frames, "contact_sheets": sheets}
    atomic_write(directory / "manifest.json", json.dumps(manifest, indent=2))
    brief = f"""# Caption task: {project.title}

Project ID: {project.id}
Video: {project.video.path}
Duration: {project.video.duration:.3f} seconds
Current revision: {project.revision}

Read manifest.json and view the contact sheets with your image inspection tool.
These are sampled frames, not a complete account of the recording. Inspect
additional frames around transitions with `./clarity-cli frame {project.id} --time SECONDS`.
Use `--width 0` for original resolution when small UI text is hard to read.
Write concise explanations of visible screen actions. Do not invent clicks,
features, outcomes, or motivations that the recording does not establish.
Ask for context when an action's purpose is unclear. Never claim to have heard
audio from the contact sheets. Prefer one short explanation per meaningful action.

Save a JSON array of {{"start": 0.0, "end": 3.5, "text": "Explanation."}} entries.
Use seconds, end > start, no overlaps, and end <= {project.video.duration:.3f}.
Omit id for new entries; retain id when editing an existing caption.
Inspect existing captions first: `./clarity-cli show {project.id}`.
Apply using the current revision (reload if it has changed):
`./clarity-cli cues {project.id} --file /absolute/path/cues.json --revision REVISION`
Then `./clarity-cli validate {project.id}` and export SRT for review.
Do not call narration unless the user authorizes use of their OpenRouter credits.
"""
    atomic_write(directory / "AI-BRIEF.md", brief)
    return {**manifest, "manifest": str(directory / "manifest.json"), "brief": str(directory / "AI-BRIEF.md")}


def doctor() -> dict:
    result = {name: executable(name) for name in ("ffmpeg", "ffprobe")}
    result["subtitle_rendering"] = False
    if result["ffmpeg"]:
        filters = run(["ffmpeg", "-hide_banner", "-filters"], 30)
        result["subtitle_rendering"] = " subtitles " in filters
    result["ready"] = bool(result["ffmpeg"] and result["ffprobe"] and result["subtitle_rendering"])
    return result
