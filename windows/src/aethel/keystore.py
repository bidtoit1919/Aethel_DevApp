"""API keys for Settings > Accounts, kept in Windows Credential Manager
(as "Aethel/api-keys/<provider>"), never in Aethel's database, the ledger
or any file. One entry per provider.

These calls go through winplat (ctypes on advapi32); callers run them off
the main thread like the Linux edition's keyring calls."""

from . import winplat

_SCOPE = "api-keys"


class KeyStoreError(Exception):
    pass


def get(provider: str) -> str | None:
    try:
        return winplat.get_secret(_SCOPE, provider)
    except winplat.SecretStoreError as error:
        raise KeyStoreError(str(error)) from None


def set(provider: str, key: str) -> None:
    try:
        winplat.set_secret(_SCOPE, provider, key)
    except winplat.SecretStoreError as error:
        raise KeyStoreError(str(error)) from None


def delete(provider: str) -> None:
    try:
        winplat.delete_secret(_SCOPE, provider)
    except winplat.SecretStoreError as error:
        raise KeyStoreError(str(error)) from None


def providers() -> list[str]:
    """Providers that have a key stored."""
    try:
        return winplat.secret_names(_SCOPE)
    except winplat.SecretStoreError as error:
        raise KeyStoreError(str(error)) from None
