import io
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from clarity.media import doctor, frame, inspect_video, probe, run
from clarity.models import Cue, Project, Video, subtitle_text, timestamp
from clarity.output import browser_preview, export, narrate, narration_manifest, narration_status, narration_track, render, text_hash
from clarity.server import create_app
from clarity.store import ConflictError, Store, atomic_write


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "projects")


@pytest.fixture
def project(store, tmp_path):
    return store.create(Video(path=str(tmp_path / "video.mp4"), name="video.mp4", duration=12, width=640, height=360), "Test recording")


def test_precision_and_subtitle_formats(store, project):
    updated = store.update(project.id, [Cue(start=0.9996, end=2.125, text="Open <Settings> & choose a language.\nThen continue.")], 0)
    assert timestamp(3599.9996) == "01:00:00,000"
    assert "00:00:01,000 --> 00:00:02,125" in subtitle_text(updated, "srt")
    assert "&lt;Settings&gt; &amp;" in subtitle_text(updated, "vtt")
    assert subtitle_text(updated, "vtt").startswith("WEBVTT\n")
    assert json.loads(subtitle_text(updated, "json"))["revision"] == 1
    assert export(store, updated).read_text().endswith("Then continue.\n")


def test_blank_lines_cannot_break_subtitle_blocks():
    cue = Cue(start=0, end=3, text="First line.\n \n\t\nSecond line.")
    assert cue.text == "First line.\nSecond line."


@pytest.mark.parametrize("start,end,text", [(1,1,"x"), (-1,2,"x"), (0,math.inf,"x"), (math.nan,2,"x"), (0,1,"   "), (0,1,"\x00")])
def test_reject_invalid_caption_values(start,end,text):
    with pytest.raises(ValidationError):
        Cue(start=start, end=end, text=text)


def test_revision_conflicts_validation_and_history(store, project):
    cue = Cue(start=1, end=3, text="Open the settings.")
    updated = store.update(project.id, [cue], 0)
    with pytest.raises(ConflictError):
        store.update(project.id, [], 0)
    with pytest.raises(ValueError, match="overlap"):
        store.update(project.id, [cue, Cue(start=2, end=4, text="Next")], 1)
    with pytest.raises(ValueError, match="beyond"):
        store.update(project.id, [Cue(start=11, end=13, text="Next")], 1)
    with pytest.raises(ValueError, match="Duplicate"):
        store.update(project.id, [cue, Cue(id=cue.id,start=4,end=5,text="Next")], 1)
    assert store.get(project.id).revision == 1
    history = json.loads((store.directory(project.id) / "history/000000.json").read_text())
    assert history["cues"] == []
    assert updated.cues[0].id == cue.id


def test_file_boundaries(store, project, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("not an asset")
    (store.directory(project.id) / "escape").symlink_to(outside)
    with pytest.raises(ValueError):
        store.directory("../outside")
    for path in ("../../secret.txt", "escape", str(outside)):
        with pytest.raises(FileNotFoundError):
            store.asset(project.id, path)


def test_http_ranges_conflict_and_local_origin(store, project, tmp_path):
    media = Path(project.video.path)
    media.write_bytes(b"0123456789")
    with TestClient(create_app(store)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").json()["app"] == "clarity-studio"
        response = client.get(f"/api/projects/{project.id}/media", headers={"Range":"bytes=2-5"})
        assert response.status_code == 206 and response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert client.get(f"/api/projects/{project.id}/media", headers={"Range":"bytes=20-30"}).status_code == 416
        payload = {"revision":0,"cues":[{"start":0,"end":3,"text":"Hello"}]}
        response = client.put(f"/api/projects/{project.id}/cues", json=payload)
        assert response.status_code == 200
        assert client.put(f"/api/projects/{project.id}/cues", json=payload).status_code == 409
        assert client.post("/api/projects", json={"path":"/secret"}, headers={"Origin":"https://example.com"}).status_code == 403
        assert client.get("/api/projects", headers={"Host":"attacker.example"}).status_code == 400
        assert client.get(f"/api/projects/{project.id}/export/srt").text.endswith("Hello\n")
        assert client.get(f"/api/projects/{project.id}/export/exe").status_code == 400
        assert client.post("/api/upload", files={"file":("bad.exe",b"x")}).status_code == 400


@pytest.fixture(scope="module")
def real_video(tmp_path_factory):
    if not doctor()["ready"]:
        pytest.skip("FFmpeg with libass is required for integration tests")
    directory = tmp_path_factory.mktemp("media ' with spaces")
    path = directory / "recording ' test.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x25432c:s=640x360:r=12:d=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])
    return path


def test_complete_media_pipeline(store, real_video):
    project = store.create(probe(real_video), "Media pipeline")
    project = store.update(project.id, [Cue(start=0.2, end=2.7, text="Open Settings & choose a language.")], 0)
    image = frame(store, project, 0.5)
    assert image.read_bytes().startswith(b"\xff\xd8")
    with pytest.raises(ValueError):
        frame(store, project, project.video.duration)
    inspection = inspect_video(store, project, every=0.2, max_frames=3)
    assert len(inspection["frames"]) == 3
    assert inspection["frames"][-1]["time"] >= 2
    assert Path(inspection["contact_sheets"][0]).is_file()
    assert "Do not invent" in Path(inspection["brief"]).read_text()
    output = render(store, project)
    assert probe(output).has_audio
    assert abs(probe(output).duration - project.video.duration) < 0.1
    # Check for actual white subtitle glyphs in the lower video, not merely
    # a changed checksum that could come from recompression alone.
    from PIL import Image
    captioned_project = store.create(probe(output))
    with Image.open(frame(store, captioned_project, 1, width=0)) as image:
        crop = image.convert("RGB").crop((0, image.height - 100, image.width, image.height))
        assert sum(r > 210 and g > 210 and b > 210 for r,g,b in crop.getdata()) > 50
    assert probe(browser_preview(store, project)).width <= 1280


def wav_bytes(duration):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1,2,48000,0,"NONE","not compressed"))
        audio.writeframes(b"\x01\x00" * round(duration * 48000))
    return stream.getvalue()


def test_mocked_narration_cache_overflow_and_stale(store, real_video, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-not-a-real-key")
    project = store.create(probe(real_video))
    project = store.update(project.id,[Cue(start=0.3,end=1.5,text="First explanation."),Cue(start=1.6,end=2.9,text="Second explanation.")],0)
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=wav_bytes(0.8), headers={"Content-Type":"audio/wav"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = narrate(store,project,"test-voice",client=client)
        assert all(s["status"] == "ready" for s in result["segments"])
        narrate(store,project,"test-voice",client=client)
        assert len(requests) == 2  # Reuses the generated segments without another paid call.
        track = store.directory(project.id) / "track.wav"
        narration_track(store,project,track)
        with wave.open(str(track)) as audio:
            assert audio.readframes(14400) == b"\0\0" * 14400
            assert audio.readframes(1) != b"\0\0"
            assert audio.getnframes() == round(project.video.duration * 48000)
        assert probe(render(store,project,narrated=True)).has_audio
        changed = project.model_dump()
        changed["cues"][0]["end"] = 0.7
        shortened = Project.model_validate(changed)
        assert narration_status(store,shortened)[0]["status"] == "overflow"
        with pytest.raises(ValueError, match="too long"):
            narration_track(store,shortened,track)
        changed["cues"][0]["text"] = "An edited explanation."
        assert narration_status(store,Project.model_validate(changed))[0]["status"] == "stale"


def test_narration_configuration_and_error_redaction(store, project, monkeypatch):
    project = store.update(project.id,[Cue(start=0,end=3,text="Explanation.")],0)
    monkeypatch.delenv("OPENROUTER_API_KEY",raising=False)
    with pytest.raises(ValueError,match="OPENROUTER_API_KEY"):
        narrate(store,project,"voice")
    monkeypatch.setenv("OPENROUTER_API_KEY","secret-test-key")
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401,text="secret-test-key must not appear"))) as client:
        with pytest.raises(ValueError) as result:
            narrate(store,project,"voice",client=client)
        assert "401" in str(result.value)
        assert "secret-test-key" not in str(result.value)


def test_upload_and_cli_roundtrip(store, real_video, monkeypatch):
    with TestClient(create_app(store)) as client:
        response = client.post("/api/upload",files={"file":("recording.mp4",real_video.read_bytes(),"video/mp4")})
        assert response.status_code == 201
        project = response.json()
        assert Path(project["video"]["path"]).is_file()
    monkeypatch.setenv("CLARITY_PROJECTS_DIR",str(store.root))
    command = [sys.executable,"-m","clarity"]
    result = subprocess.run([*command,"show",project["id"]],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)["id"] == project["id"]
    cues = store.root / "input.json"
    cues.write_text(json.dumps([{"start":0.2,"end":2,"text":"Explain this action."}]))
    result = subprocess.run([*command,"cues",project["id"],"--file",str(cues),"--revision","0"],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)["revision"] == 1
    conflict = subprocess.run([*command,"cues",project["id"],"--file",str(cues),"--revision","0"],capture_output=True,text=True)
    assert conflict.returncode == 1 and "current revision 1" in json.loads(conflict.stderr)["error"]
