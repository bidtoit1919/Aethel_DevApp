"""API keys for Settings > Accounts, kept in the desktop keyring (libsecret),
never in Aethel's database, the ledger or any file. One entry per provider.

These calls can block while the keyring unlocks, so callers run them off
the main thread (accounts.refresh, the launch preparation, model calls)."""

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret

SCHEMA = Secret.Schema.new(
    "com.example.Aethel.ApiKey",
    Secret.SchemaFlags.NONE,
    {"provider": Secret.SchemaAttributeType.STRING},
)


class KeyStoreError(Exception):
    pass


def get(provider: str) -> str | None:
    try:
        return Secret.password_lookup_sync(SCHEMA, {"provider": provider}, None)
    except Exception as error:  # GLib.Error from a locked or missing keyring
        raise KeyStoreError(f"The keyring could not be read: {error}") from None


def set(provider: str, key: str) -> None:
    try:
        Secret.password_store_sync(SCHEMA, {"provider": provider}, Secret.COLLECTION_DEFAULT,
                                   f"Aethel API key: {provider}", key, None)
    except Exception as error:
        raise KeyStoreError(f"The keyring refused the key: {error}") from None


def delete(provider: str) -> None:
    try:
        Secret.password_clear_sync(SCHEMA, {"provider": provider}, None)
    except Exception as error:
        raise KeyStoreError(f"The keyring could not remove the key: {error}") from None


def providers() -> list[str]:
    """Providers that have a key stored."""
    try:
        items = Secret.password_search_sync(SCHEMA, {}, Secret.SearchFlags.ALL, None)
    except Exception as error:
        raise KeyStoreError(f"The keyring could not be read: {error}") from None
    return sorted({i.get_attributes().get("provider", "") for i in items} - {""})
