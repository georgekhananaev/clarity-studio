from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
import urllib.request
from pathlib import Path

from .media import doctor, frame, inspect_video, probe
from .models import Cue
from .output import export, export_audio, narrate, narration_status, render
from .speech import SpeechService
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Clarity Studio — inspect recordings, write timed explanations, and export subtitles. All results are JSON.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check video tools and narration configuration")
    sub.add_parser("list", help="List local projects")
    sub.add_parser("speech-settings", help="Read speech connection preferences and key status (never the keys)")
    command = sub.add_parser("speech-models", help="Discover speech models and voices without generating audio")
    command.add_argument("--provider", choices=["openrouter", "local"], default="openrouter")
    command.add_argument("--base-url", help="Local speech API base URL, such as http://127.0.0.1:8880/v1")
    command.add_argument("--model", help="Fetch local voices for a specific model")
    command = sub.add_parser("import", help="Import a local video by absolute path; leaves the original in place")
    command.add_argument("video", type=Path)
    command.add_argument("--title")
    for name in ("show", "validate", "inspect", "frame", "cues", "add", "export", "render", "narrate", "audio"):
        command = sub.add_parser(name)
        command.add_argument("project")
        if name == "inspect":
            command.add_argument("--every", type=float, default=5)
            command.add_argument("--max-frames", type=int, default=48)
        if name == "frame":
            command.add_argument("--time", type=float, required=True)
            command.add_argument("--width", type=int, default=1600, help="Maximum image width; use 0 for original resolution")
        if name == "cues":
            command.add_argument("--file", type=Path, required=True, help="JSON array or object with a cues array")
            command.add_argument("--revision", type=int, required=True, help="Revision last read with show; prevents overwriting newer edits")
        if name == "add":
            command.add_argument("--start", type=float, required=True)
            command.add_argument("--end", type=float, required=True)
            command.add_argument("--text", required=True)
        if name == "export":
            command.add_argument("--format", choices=["srt", "vtt", "json", "txt"], default="srt")
        if name == "render":
            command.add_argument("--narrated", action="store_true", help="Replace original audio with generated narration")
        if name == "narrate":
            command.add_argument("--provider", choices=["openrouter", "local"])
            command.add_argument("--voice")
            command.add_argument("--model")
            command.add_argument("--instructions")
            command.add_argument("--cue", action="append", help="Generate only these caption IDs; may be repeated")
        if name == "audio":
            command.add_argument("--format", choices=["mp3", "wav"], default="mp3")
    command = sub.add_parser("serve", help="Start the local review app and HTTP API")
    command.add_argument("--port", type=int, default=8765)
    command.add_argument("--open", action="store_true")
    args = parser.parse_args()
    store = Store()
    speech = SpeechService(store)
    try:
        if args.command == "serve":
            import uvicorn
            from .server import create_app
            from .store import ROOT
            if not 1 <= args.port <= 65535:
                raise ValueError("Port must be between 1 and 65535.")
            url = f"http://localhost:{args.port}"
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                    running = json.load(response)
            except (OSError, ValueError):
                running = None
            if running and running.get("app") == "clarity-studio" and running.get("workspace") == str(ROOT):
                if args.open:
                    webbrowser.open(url)
                print(json.dumps({"url": url, "status": "already running"}))
                return
            if args.open:
                threading.Timer(1, lambda: webbrowser.open(url)).start()
            uvicorn.run(create_app(store), host="127.0.0.1", port=args.port, access_log=False)
            return
        if args.command == "doctor":
            result = {**doctor(), "narration_configured": bool(os.environ.get("OPENROUTER_API_KEY")), "projects_directory": str(store.root)}
        elif args.command == "list":
            result = [project.model_dump() for project in store.list()]
        elif args.command == "speech-settings":
            result = speech.public_settings()
        elif args.command == "speech-models":
            result = speech.discover(args.provider, args.base_url, args.model)
        elif args.command == "import":
            result = store.create(probe(args.video), args.title).model_dump()
        else:
            project = store.get(args.project)
            if args.command == "show":
                result = {**project.model_dump(), "warnings": project.warnings(), "narration": narration_status(store, project)}
            elif args.command == "validate":
                result = {"valid": True, "revision": project.revision, "warnings": project.warnings(), "narration": narration_status(store, project)}
            elif args.command == "inspect":
                result = inspect_video(store, project, args.every, args.max_frames)
            elif args.command == "frame":
                result = {"path": str(frame(store, project, args.time, args.width)), "time": args.time}
            elif args.command == "cues":
                data = json.loads(args.file.read_text())
                cues = data["cues"] if isinstance(data, dict) else data
                result = store.update(project.id, [Cue.model_validate(cue) for cue in cues], args.revision).model_dump()
            elif args.command == "add":
                cue = Cue(start=args.start, end=args.end, text=args.text)
                result = store.update(project.id, [*project.cues, cue], project.revision).model_dump()
            elif args.command == "export":
                result = {"path": str(export(store, project, args.format))}
            elif args.command == "render":
                result = {"path": str(render(store, project, args.narrated))}
            elif args.command == "narrate":
                connection, model, voice, instructions = speech.resolve(args.provider, args.model, args.voice, args.instructions)
                result = narrate(store, project, voice, model, instructions, connection=connection, cue_ids=args.cue)
            elif args.command == "audio":
                result = {"path": str(export_audio(store, project, args.format))}
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
