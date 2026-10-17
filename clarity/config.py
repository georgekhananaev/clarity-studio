"""Private, transactional local preferences. Secrets belong in the OS Keychain."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable


class ConfigError(ValueError):
    """A safe configuration error that never includes stored values."""


def _preferences_json(value: Any) -> str:
    # A second boundary beyond the validated API models: accidental credential
    # fields must not become plaintext SQLite values, including nested fields.
    sensitive = {"apikey", "token", "accesstoken", "refreshtoken", "password", "secret", "authorization", "credential", "credentials"}

    def check(item):
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = re.sub(r"[^a-z0-9]", "", key.lower()) if isinstance(key, str) else ""
                if not isinstance(key, str) or normalized in sensitive or normalized.endswith(("apikey", "token", "password", "secret", "privatekey")):
                    raise ConfigError("Credentials cannot be stored in the preferences database. Use macOS Keychain.")
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)

    check(value)
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ConfigError("Preferences must contain valid JSON values.") from None


class ConfigStore:
    """Namespaces of nonsecret JSON preferences under one project store.

    A separate connection per operation supports the threaded local API and CLI.
    Writes and first-time migration use SQLite transactions; no cached values can
    overwrite preferences saved by another process.
    """

    def __init__(self, root: Path):
        self.directory = Path(root) / ".local"
        self.path = self.directory / "settings.sqlite3"
        try:
            if self.directory.is_symlink():
                raise ConfigError("The local configuration directory must not be a symbolic link.")
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            self.directory.chmod(0o700)
            # Create with private permissions before SQLite can write any data.
            # O_NOFOLLOW also rejects a symlink at the database filename.
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            with self._connection() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > 1:
                    raise ConfigError("This configuration database requires a newer version of Clarity Studio.")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS preferences (namespace TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
        except OSError:
            raise ConfigError("Could not open the private local configuration database. Check its permissions.") from None

    @contextmanager
    def _connection(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
        except sqlite3.Error:
            raise ConfigError("Could not read or save local preferences. Existing files were preserved; check the configuration database.") from None
        finally:
            if connection is not None:
                connection.close()  # Any uncommitted transaction rolls back.

    @staticmethod
    def _namespace(namespace: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", namespace):
            raise ConfigError("Invalid preferences namespace.")

    def get(self, namespace: str, default: Any = None) -> Any:
        self._namespace(namespace)
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM preferences WHERE namespace = ?", (namespace,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            raise ConfigError("Saved preferences are invalid. Existing files were preserved.") from None

    def set(self, namespace: str, value: Any) -> None:
        self._namespace(namespace)
        payload = _preferences_json(value)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO preferences (namespace, value) VALUES (?, ?) ON CONFLICT(namespace) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP", (namespace, payload))
            connection.commit()

    def update(self, namespace: str, patch: dict) -> dict:
        """Atomically merge a partial object without losing concurrent changes."""
        self._namespace(namespace)
        if not isinstance(patch, dict):
            raise ConfigError("A preferences update must be a JSON object.")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT value FROM preferences WHERE namespace = ?", (namespace,)).fetchone()
            try:
                current = json.loads(row[0]) if row else {}
            except (ValueError, TypeError):
                raise ConfigError("Saved preferences are invalid. Existing files were preserved.") from None
            if not isinstance(current, dict):
                raise ConfigError("Only object preferences can receive a partial update.")
            updated = {**current, **patch}
            payload = _preferences_json(updated)
            connection.execute("INSERT INTO preferences (namespace, value) VALUES (?, ?) ON CONFLICT(namespace) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP", (namespace, payload))
            connection.commit()
            return updated

    def import_legacy(self, namespace: str, path: Path, validate: Callable[[Any], Any]) -> bool:
        """Import once, without overriding SQLite or deleting the source backup.

        Validation runs before the insert. A failed or interrupted migration can
        be retried, and the original JSON remains available for recovery.
        """
        self._namespace(namespace)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM preferences WHERE namespace = ?", (namespace,)).fetchone() or not path.is_file():
                return False
            try:
                value = validate(json.loads(path.read_text(encoding="utf-8")))
                payload = _preferences_json(value)
            except (OSError, ValueError, TypeError):
                raise ConfigError("Could not migrate saved preferences. The original settings file was preserved.") from None
            connection.execute("INSERT INTO preferences (namespace, value) VALUES (?, ?)", (namespace, payload))
            connection.commit()
            return True
