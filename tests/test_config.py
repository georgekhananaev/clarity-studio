import json
import sqlite3
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from clarity.config import ConfigError, ConfigStore


def test_preferences_survive_restart_and_are_isolated(tmp_path):
    first = ConfigStore(tmp_path / "first")
    assert first.get("editor", {"font_size": 18}) == {"font_size": 18}
    first.set("editor", {"font_size": 20, "label": "Clarity — 字幕"})
    restarted = ConfigStore(tmp_path / "first")
    assert restarted.get("editor") == {"font_size": 20, "label": "Clarity — 字幕"}
    assert ConfigStore(tmp_path / "second").get("editor") is None
    assert first.path == tmp_path / "first" / ".local" / "settings.sqlite3"


def test_configuration_has_private_permissions_even_when_existing(tmp_path):
    config = ConfigStore(tmp_path)
    assert stat.S_IMODE(config.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.path.stat().st_mode) == 0o600
    config.directory.chmod(0o755)
    config.path.chmod(0o644)
    ConfigStore(tmp_path)
    assert stat.S_IMODE(config.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.path.stat().st_mode) == 0o600


def test_configuration_rejects_symlink_targets(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root = tmp_path / "projects"
    root.mkdir()
    (root / ".local").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ConfigError, match="symbolic link"):
        ConfigStore(root)
    (root / ".local").unlink()
    (root / ".local").mkdir()
    target = elsewhere / "private.db"
    target.write_text("untouched")
    (root / ".local" / "settings.sqlite3").symlink_to(target)
    with pytest.raises(ConfigError):
        ConfigStore(root)
    assert target.read_text() == "untouched"


def test_legacy_migration_does_not_overwrite_or_delete_original(tmp_path):
    legacy = tmp_path / "_settings.json"
    legacy.write_text(json.dumps({"font_size": 18}))
    config = ConfigStore(tmp_path)
    assert config.import_legacy("editor", legacy, lambda value: value)
    assert config.get("editor") == {"font_size": 18}
    assert legacy.is_file()
    config.set("editor", {"font_size": 24})
    legacy.write_text("invalid JSON from obsolete file")
    assert not config.import_legacy("editor", legacy, lambda value: value)
    assert config.get("editor") == {"font_size": 24}


def test_failed_migration_preserves_source_and_can_be_retried(tmp_path):
    config = ConfigStore(tmp_path)
    legacy = tmp_path / "_settings.json"
    legacy.write_text('{"api_key":"secret-migration-value"}')
    with pytest.raises(ConfigError, match="preserved") as error:
        config.import_legacy("editor", legacy, lambda value: value)
    assert "secret-migration-value" not in str(error.value)
    assert config.get("editor") is None
    assert legacy.is_file()
    assert b"secret-migration-value" not in config.path.read_bytes()
    legacy.write_text('{"font_size":18}')
    assert config.import_legacy("editor", legacy, lambda value: value)


@pytest.mark.parametrize("field", ["api_key", "token", "openrouter_api_key", "accessToken", "password", "authorization", "client_secret"])
def test_database_refuses_nested_credential_fields(tmp_path, field):
    config = ConfigStore(tmp_path)
    with pytest.raises(ConfigError, match="Keychain"):
        config.set("speech", {"nested": [{field: "private-value-never-written"}]})
    assert b"private-value-never-written" not in config.path.read_bytes()
    assert config.get("speech") is None


def test_failed_write_rolls_back_and_does_not_overwrite_preferences(tmp_path):
    config = ConfigStore(tmp_path)
    config.set("editor", {"font_size": 18})
    with sqlite3.connect(config.path) as connection:
        connection.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON preferences BEGIN SELECT RAISE(ABORT, 'forced failure'); END")
    with pytest.raises(ConfigError):
        config.set("editor", {"font_size": 20})
    assert config.get("editor") == {"font_size": 18}


def test_atomic_updates_preserve_concurrent_partial_changes(tmp_path):
    stores = [ConfigStore(tmp_path) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda item: item[1].update("editor", {f"preference_{item[0]}": item[0]}), enumerate(stores)))
    assert ConfigStore(tmp_path).get("editor") == {f"preference_{i}": i for i in range(12)}


def test_corrupt_database_is_not_replaced(tmp_path):
    directory = tmp_path / ".local"
    directory.mkdir()
    path = directory / "settings.sqlite3"
    path.write_bytes(b"not a database")
    with pytest.raises(ConfigError, match="preserved"):
        ConfigStore(tmp_path)
    assert path.read_bytes() == b"not a database"


def test_gitignore_protects_local_files_and_keeps_source(tmp_path):
    # An isolated temporary repository; never initialize or mutate the workspace.
    root = Path(__file__).resolve().parent.parent
    (tmp_path / ".gitignore").write_text((root / ".gitignore").read_text())
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    ignored = ["projects/demo/project.json", "projects/.local/settings.sqlite3", ".local/settings.sqlite3-wal", ".env", ".env.production", "credentials.json", "sample.mov", "narration.wav", "captions.srt", "Aegisub.app/Contents/MacOS/Aegisub", "tmp/screenshot.png", "trace.log", "clarity/__pycache__/config.pyc", ".venv/bin/python", ".improve-loop/run/screenshot.png"]
    source = ["uv.lock", "pyproject.toml", "clarity/config.py", "web/logo.svg", "tests/test_config.py", ".env.example", ".env.sample", ".env.template"]
    result = subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "--no-index", "--", *ignored, *source], check=True, capture_output=True, text=True)
    assert set(result.stdout.splitlines()) == set(ignored)
