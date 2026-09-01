"""Small flat key-value store for non-secret dashboard preferences.

Unlike sftp_config.py this is plaintext — nothing stored here is sensitive
(currently: whether "Deploy (build)" takes a safety backup first).
"""

from __future__ import annotations

import json
import os
import threading

from .config import settings

_lock = threading.Lock()


def _path() -> str:
	return os.path.join(settings.data_dir, "prefs.json")


def _read() -> dict:
	try:
		with open(_path()) as fh:
			return json.load(fh)
	except (OSError, ValueError):
		return {}


def get(key: str, default=None):
	with _lock:
		return _read().get(key, default)


def set(key: str, value) -> None:
	with _lock:
		data = _read()
		data[key] = value
		os.makedirs(settings.data_dir, exist_ok=True)
		tmp = _path() + ".tmp"
		with open(tmp, "w") as fh:
			json.dump(data, fh)
		os.replace(tmp, _path())
