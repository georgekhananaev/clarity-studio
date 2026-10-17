import pytest

from clarity.speech import Credentials


class MemoryKeychain:
    def __init__(self):
        self.items = {}

    def get_password(self, service, account):
        return self.items.get((service, account))

    def set_password(self, service, account, value):
        self.items[service, account] = value

    def delete_password(self, service, account):
        del self.items[service, account]


@pytest.fixture(autouse=True)
def isolated_keychain(monkeypatch):
    """Tests must never read or write the user's real Keychain."""
    backend = MemoryKeychain()
    monkeypatch.setattr(Credentials, "keychain", staticmethod(lambda: backend))
    return backend
