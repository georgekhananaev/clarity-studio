from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from clarity.server import create_app
from clarity.store import Store


def test_editor_preferences_persist_and_patch_without_resetting_other_choices(tmp_path):
    store = Store(tmp_path)
    client = TestClient(create_app(store))
    defaults = client.get('/api/preferences').json()
    assert defaults['appearance'] == 'dark'
    assert defaults['playback_speed'] == 1
    assert defaults['storage']['database'] == str(tmp_path / '.local' / 'settings.sqlite3')
    assert client.put('/api/preferences', json={'appearance': 'light', 'playback_speed': 1.5}).status_code == 200
    assert client.put('/api/preferences', json={'last_project': 'sample-123', 'muted': True}).status_code == 200
    restarted = TestClient(create_app(Store(tmp_path))).get('/api/preferences').json()
    assert restarted['appearance'] == 'light'
    assert restarted['playback_speed'] == 1.5
    assert restarted['last_project'] == 'sample-123'
    assert restarted['muted'] is True
    assert restarted['caption_size'] == 22


def test_editor_preferences_reject_credentials_and_invalid_options_without_echoing_values(tmp_path):
    client = TestClient(create_app(Store(tmp_path)))
    for value in [{'appearance': 'unknown'}, {'playback_speed': 1.234}, {'caption_size': 999}, {'last_project': '../../private'}, {'api_key': 'private-key-value'}, {'muted': None, 'nested': {'token': 'private-key-value'}}]:
        response = client.put('/api/preferences', json=value)
        assert response.status_code == 422
        assert 'private-key-value' not in response.text
    database = tmp_path / '.local' / 'settings.sqlite3'
    assert b'private-key-value' not in database.read_bytes()
    assert client.get('/api/preferences').json()['appearance'] == 'dark'


def test_preferences_are_local_only_and_never_browser_cacheable(tmp_path):
    client = TestClient(create_app(Store(tmp_path)))
    assert client.put('/api/preferences', json={'appearance': 'light'}, headers={'Origin': 'https://elsewhere.example'}).status_code == 403
    assert client.get('/api/preferences', headers={'Host': 'elsewhere.example'}).status_code == 400
    result = client.get('/api/preferences')
    assert result.headers['cache-control'] == 'no-store'
    assert result.json()['appearance'] == 'dark'


def test_editor_preference_updates_from_two_app_instances_preserve_independent_fields(tmp_path):
    one = TestClient(create_app(Store(tmp_path)))
    two = TestClient(create_app(Store(tmp_path)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(one.put, '/api/preferences', json={'appearance': 'light'}), pool.submit(two.put, '/api/preferences', json={'playback_speed': 2})]
        assert all(future.result().status_code == 200 for future in requests)
    values = one.get('/api/preferences').json()
    assert values['appearance'] == 'light'
    assert values['playback_speed'] == 2


def test_speech_choice_background_patch_cannot_modify_connection_or_credentials(tmp_path):
    from clarity.speech import SpeechService, SpeechSettings
    store = Store(tmp_path)
    speech = SpeechService(store)
    settings = SpeechSettings(provider='local', local_base_url='http://127.0.0.1:8000/v1')
    speech.save(settings, 'private-session-key', remember=False)
    client = TestClient(create_app(store, speech))
    payload = {'provider': 'local', 'preferences': {'model': 'kokoro', 'voice': 'af_heart'}}
    response = client.patch('/api/speech/preferences', json=payload)
    assert response.status_code == 200
    assert response.json()['local_base_url'] == settings.local_base_url
    assert response.json()['keys']['local']['source'] == 'session'
    assert 'private-session-key' not in response.text
    assert speech.settings().local.model == 'kokoro'
    assert speech.settings().openrouter.model == 'fish-audio/drama-3'
    for private_field in ['api_key', 'local_base_url', 'remember_key']:
        invalid = client.patch('/api/speech/preferences', json={**payload, private_field: 'private-session-key'})
        assert invalid.status_code == 422
        assert 'private-session-key' not in invalid.text
    assert b'private-session-key' not in speech.config.path.read_bytes()


def test_background_speech_choices_preserve_environment_connection_default(tmp_path, monkeypatch):
    monkeypatch.setenv('CLARITY_LOCAL_BASE_URL', 'http://127.0.0.1:9000/v1')
    client = TestClient(create_app(Store(tmp_path)))
    response = client.patch('/api/speech/preferences', json={'provider': 'local', 'preferences': {'model': 'kokoro', 'voice': 'af_heart'}})
    assert response.status_code == 200
    assert response.json()['local_base_url'] == 'http://127.0.0.1:9000/v1'


def test_layout_preferences_survive_restart_and_reject_unusable_sizes(tmp_path):
    client = TestClient(create_app(Store(tmp_path)))
    response = client.put('/api/preferences', json={'sidebar_collapsed': True, 'preview_share': 0.7, 'preferences_pane': 'integrations'})
    assert response.status_code == 200
    restarted = TestClient(create_app(Store(tmp_path))).get('/api/preferences').json()
    assert restarted['sidebar_collapsed'] is True
    assert restarted['preview_share'] == 0.7
    assert restarted['preferences_pane'] == 'integrations'
    for patch in [{'preview_share': 0.3}, {'preview_share': 0.9}, {'preferences_pane': 'missing'}]:
        assert client.put('/api/preferences', json=patch).status_code == 422
    assert client.get('/api/preferences').json()['preview_share'] == 0.7


def test_sidebar_width_persists_with_valid_bounds(tmp_path):
    client = TestClient(create_app(Store(tmp_path)))
    assert client.get('/api/preferences').json()['sidebar_width'] == 216
    result = client.put('/api/preferences', json={'sidebar_width': 288})
    assert result.status_code == 200
    restarted = TestClient(create_app(Store(tmp_path))).get('/api/preferences').json()
    assert restarted['sidebar_width'] == 288
    for width in [167, 361, True, 'wide']:
        assert client.put('/api/preferences', json={'sidebar_width': width}).status_code == 422
    assert client.get('/api/preferences').json()['sidebar_width'] == 288
