"""Small flat key-value store for non-secret dashboard preferences.

Unlike the secrets in ftp_config.py this is plaintext — nothing stored here is
sensitive (currently: whether "Deploy (build)" takes a safety backup first).
Rows live in the `kv` table of the ops database (store.py); the older
prefs.json is imported on first boot.
"""

from __future__ import annotations

from . import store


def get(key: str, default=None):
	return store.kv_get(key, default)


def set(key: str, value) -> None:
	store.kv_set(key, value)
