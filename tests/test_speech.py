import json
import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from clarity.models import Cue, Video
from clarity.output import export_audio, narrate, narration_manifest, narration_status
from clarity.server import create_app
from clarity.speech import Connection, Credentials, SpeechService, SpeechSettings, local_url
from clarity.store import Store


@pytest.fixture
def speech(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CLARITY_LOCAL_API_KEY", raising=False)
    return SpeechService(Store(tmp_path / "projects"))


def test_cloud_catalog_only_speech_voice_metadata_and_offline_cache(speech):
    entries = [
        {"id":"text/chat", "architecture":{"output_modalities":["text"]}},
        {"id":"example/voice", "name":"Example Voice", "architecture":{"output_modalities":["speech"]}, "supported_voices":["one", {"id":"two", "name":"Second voice"}]},
        {"id":"fish-audio/drama-3", "name":"Drama 3", "architecture":{"output_modalities":["speech"]}, "supported_voices":None},
    ]
    def respond(request):
        assert request.url.params["output_modalities"] == "speech"
        assert "authorization" not in request.headers
        return httpx.Response(200,json={"data":entries})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = speech.discover(client=client)
    assert [m["id"] for m in result["models"]] == ["fish-audio/drama-3","example/voice"]
    assert result["models"][1]["voices"][1] == {"id":"two","name":"Second voice"}
    def offline(request):
        raise httpx.ConnectError("offline")
    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        fallback = speech.discover(client=client)
    assert fallback["cached"] and len(fallback["models"]) == 2


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://169.254.169.254/v1", "http://user:password@localhost:8880/v1", "file:///etc/passwd", "http://localhost/v1?token=secret", "http://localhost:99999/v1", "http://localhost/#x"])
def test_local_endpoints_reject_remote_or_embedded_secrets(url):
    with pytest.raises(ValueError): local_url(url)


@pytest.mark.parametrize("url,expected", [("http://localhost:8880/","http://localhost:8880/v1"),("http://127.0.0.1:8000/v1/","http://127.0.0.1:8000/v1"),("http://[::1]:8000/v1","http://[::1]:8000/v1"),("http://192.168.110.8:8880/v1/audio/speech","http://192.168.110.8:8880/v1")])
def test_normalize_local_endpoints(url,expected):
    assert local_url(url) == expected


def test_local_discovery_does_not_receive_cloud_key(speech, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY","cloud-secret")
    def respond(request):
        assert "authorization" not in request.headers
        assert request.url.host == "127.0.0.1"
        if request.url.path.endswith("/models"):
            return httpx.Response(200,json={"data":[{"id":"kokoro","task":"text-to-speech"},{"id":"whisper","task":"automatic-speech-recognition"}]})
        return httpx.Response(200,json={"voices":["af_heart",{"id":"af_bella","name":"Bella"}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = speech.discover("local", client=client)
    assert [m["id"] for m in result["models"]] == ["kokoro"]
    assert len(result["voices"]) == 2


def test_manual_model_fallback_when_metadata_routes_absent(speech):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        result = speech.discover("local",client=client)
    assert not result["models"] and result["warnings"]


def test_settings_store_only_preferences_keys_isolated_by_endpoint(speech, isolated_keychain):
    settings = SpeechSettings()
    public = speech.save(settings, "cloud-secret", remember=True)
    assert public["keys"]["openrouter"] == {"configured":True,"source":"keychain"}
    assert b"cloud-secret" not in speech.config.path.read_bytes()
    assert not (speech.store.root / "_speech-settings.json").exists()
    assert "cloud-secret" not in json.dumps(public)
    restarted = SpeechService(speech.store)
    assert restarted.connection("openrouter").key == "cloud-secret"
    assert restarted.public_settings()["keys"]["openrouter"]["source"] == "keychain"
    settings.provider = "local"
    speech.save(settings,"local-secret")
    assert speech.connection("local").key == "local-secret"
    assert speech.connection("local","http://127.0.0.1:8001/v1").key == ""
    speech.save(settings,clear=True)
    assert not speech.connection("local").key
    assert speech.connection("openrouter").key == "cloud-secret"


@pytest.mark.parametrize("active,integration", [("openrouter", "local"), ("local", "openrouter")])
def test_configuring_other_integration_preserves_narration_provider_and_keys(speech, active, integration):
    settings = SpeechSettings(provider=active, local_base_url="http://127.0.0.1:8000/v1")
    settings.local.model = "kokoro"
    settings.local.voice = "af_heart"
    settings.openrouter.voice = "cloud-voice"
    speech.save(settings, "active-narration-test-key")
    result = speech.save(settings, "other-integration-test-key", remember=True, credential_provider=integration)
    assert result["provider"] == active
    assert result["local"]["voice"] == "af_heart"
    assert result["openrouter"]["voice"] == "cloud-voice"
    assert speech.connection(active).key == "active-narration-test-key"
    assert speech.connection(integration).key == "other-integration-test-key"
    assert result["keys"][integration] == {"configured": True, "source": "keychain"}
    assert speech.connection("local", "http://127.0.0.1:8001/v1").key == ""
    speech.save(settings, clear=True, credential_provider=integration)
    assert not speech.connection(integration).key
    assert speech.connection(active).key == "active-narration-test-key"
    assert speech.settings().provider == active
    assert b"other-integration-test-key" not in speech.config.path.read_bytes()


def test_saved_preferences_migrate_once_and_survive_restart(tmp_path):
    store = Store(tmp_path / "projects")
    original = SpeechSettings(provider="local", local_base_url="http://localhost:8000/v1")
    original.local.model = "kokoro"
    original.local.voice = "af_heart"
    legacy = store.root / "_speech-settings.json"
    legacy.write_text(original.model_dump_json())
    speech = SpeechService(store)
    assert speech.settings() == original
    assert legacy.exists()  # Recovery source is retained, but never read again.
    changed = speech.settings()
    changed.local.voice = "af_bella"
    speech.save(changed)
    legacy.write_text("broken old JSON")
    assert SpeechService(store).settings().local.voice == "af_bella"


def test_saved_credentials_and_session_keys_never_appear_in_local_files(speech, isolated_keychain):
    settings = SpeechSettings()
    speech.save(settings, "unique-keychain-key-for-test", remember=True)
    settings.provider = "local"
    speech.save(settings, "unique-session-key-for-test")
    for path in speech.store.root.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert b"unique-keychain-key-for-test" not in content
            assert b"unique-session-key-for-test" not in content
    assert SpeechService(speech.store).connection("openrouter").key == "unique-keychain-key-for-test"
    assert not SpeechService(speech.store).connection("local").key


def test_session_key_not_persisted_and_auth_test_does_not_generate(speech):
    speech.save(SpeechSettings(),"session-secret")
    assert not SpeechService(speech.store).connection("openrouter").key
    requests=[]
    def respond(request):
        requests.append(request)
        assert request.url.path == "/api/v1/key"
        return httpx.Response(200,json={"data":{"label":"private label","limit_remaining":10}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = speech.test_connection("openrouter",client=client)
    assert result["connected"] and len(requests) == 1
    assert "private label" not in json.dumps(result)
    assert "session-secret" not in repr(speech.connection("openrouter"))


def test_existing_session_key_can_be_remembered_without_reentering(speech):
    speech.save(SpeechSettings(),"remember-this-test-key")
    speech.save(SpeechSettings(),remember=True)
    restarted = SpeechService(speech.store)
    assert restarted.connection("openrouter").key == "remember-this-test-key"


def test_local_preferences_do_not_inherit_openrouter_voice(speech, monkeypatch):
    monkeypatch.setenv("OPENROUTER_VOICE", "cloud-voice-id")
    settings = SpeechSettings(provider="local")
    settings.local.model = "kokoro"
    settings.local.voice = "af_heart"
    speech.save(settings)
    connection, model, voice, _ = speech.resolve()
    assert connection.provider == "local" and model == "kokoro" and voice == "af_heart"


def test_settings_api_never_returns_credentials_and_blocks_cross_origin(speech):
    with TestClient(create_app(speech.store,speech)) as client:
        payload={"settings":SpeechSettings().model_dump(),"api_key":"secret-in-request-only"}
        response=client.put("/api/speech/settings",json=payload)
        assert response.status_code == 200
        assert "secret-in-request-only" not in response.text
        assert "secret-in-request-only" not in client.get("/api/speech/settings").text
        invalid = client.put("/api/speech/settings",json={"api_key":"secret-in-request-only"})
        assert invalid.status_code == 422 and "secret-in-request-only" not in invalid.text
        assert client.put("/api/speech/settings",json=payload,headers={"Origin":"https://attacker.example"}).status_code == 403


def test_integration_api_targets_local_credentials_without_selecting_local_narration(speech):
    settings = SpeechSettings(local_base_url="http://localhost:8000/v1")
    settings.openrouter.voice = "cloud-voice"
    speech.save(settings, "cloud-integration-test-key")
    payload = {"settings": settings.model_dump(), "credential_provider": "local", "api_key": "local-integration-test-key"}
    with TestClient(create_app(speech.store, speech)) as client:
        response = client.put("/api/speech/settings", json=payload)
        assert response.status_code == 200
        assert response.json()["provider"] == "openrouter"
        assert response.json()["openrouter"]["voice"] == "cloud-voice"
        assert response.json()["keys"]["local"] == {"configured": True, "source": "session"}
        assert "local-integration-test-key" not in response.text
        assert speech.connection("local").key == "local-integration-test-key"
        assert speech.connection("openrouter").key == "cloud-integration-test-key"
        invalid = client.put("/api/speech/settings", json={**payload, "credential_provider": "invalid"})
        assert invalid.status_code == 422
        assert "local-integration-test-key" not in invalid.text


def test_failed_authentication_api_redacts_credentials_and_never_generates_audio(speech, monkeypatch):
    secret = "private-session-key-for-auth-test"
    speech.save(SpeechSettings(), secret)
    requested = []

    def rejected(request):
        requested.append(request.url.path)
        return httpx.Response(401, json={"error": {"message": f"Rejected {secret}"}})

    original_test = speech.test_connection
    with httpx.Client(transport=httpx.MockTransport(rejected)) as transport:
        monkeypatch.setattr(speech, "test_connection", lambda provider: original_test(provider, client=transport))
        with TestClient(create_app(speech.store, speech)) as client:
            response = client.post("/api/speech/test", json={"provider": "openrouter"})
    assert response.status_code == 400
    assert "Check your API key" in response.json()["detail"]
    assert "[redacted]" in response.text and secret not in response.text
    assert requested == ["/api/v1/key"]


def test_failed_local_test_hides_transport_details(speech):
    def offline(request):
        raise httpx.ConnectError("private-local-key transport failure")

    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        with pytest.raises(ValueError, match="Could not load speech models") as failure:
            speech.test_connection("local", client=client)
    assert "private-local-key" not in str(failure.value)


def test_local_speech_generation_cache_separates_servers_and_exports_audio(speech):
    project=speech.store.create(Video(path="/unused.mp4",name="unused.mp4",duration=4,width=640,height=360))
    project=speech.store.update(project.id,[Cue(start=0.2,end=2,text="A short caption.")],0)
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as audio:
        audio.setparams((1,2,48000,0,"NONE","not compressed"))
        audio.writeframes(b"\x01\x00"*24000)
    requests=[]
    def respond(request):
        payload=json.loads(request.content)
        assert "instructions" not in payload
        assert payload["response_format"] == "wav"
        assert "authorization" not in request.headers
        requests.append(request)
        return httpx.Response(200,content=buffer.getvalue(),headers={"Content-Type":"audio/wav"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        connection=Connection("local","http://127.0.0.1:8880/v1","")
        narrate(speech.store,project,"af_heart","kokoro",client=client,connection=connection)
        narrate(speech.store,project,"af_heart","kokoro",client=client,connection=connection)
        assert len(requests) == 1
        narrate(speech.store,project,"af_heart","kokoro",client=client,connection=Connection("local","http://127.0.0.1:8881/v1",""))
        assert len(requests) == 2
    assert narration_status(speech.store,project)[0]["provider"] == "local"
    assert export_audio(speech.store,project,"mp3").stat().st_size > 0
    with wave.open(str(export_audio(speech.store,project,"wav"))) as audio:
        assert audio.getnframes() == 4*48000


def test_selected_caption_generation_does_not_generate_other_captions(speech):
    project=speech.store.create(Video(path="/unused.mp4",name="unused.mp4",duration=5,width=640,height=360))
    project=speech.store.update(project.id,[Cue(start=0,end=2,text="First."),Cue(start=2,end=4,text="Second.")],0)
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as audio:
        audio.setparams((1,2,48000,0,"NONE","not compressed"))
        audio.writeframes(b"\0\0"*2400)
    texts=[]
    def respond(request):
        texts.append(json.loads(request.content)["input"])
        return httpx.Response(200,content=buffer.getvalue())
    connection=Connection("local","http://127.0.0.1:8880/v1","")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        narrate(speech.store,project,"af_heart","kokoro",client=client,connection=connection,cue_ids=[project.cues[1].id])
        assert texts == ["Second."]
        for ids in ([], ["missing"]):
            with pytest.raises(ValueError, match="existing caption"):
                narrate(speech.store,project,"af_heart","kokoro",client=client,connection=connection,cue_ids=ids)
    assert [n["status"] for n in narration_status(speech.store,project)] == ["missing","ready"]
