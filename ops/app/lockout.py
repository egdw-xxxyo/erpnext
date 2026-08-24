"""Login throttling.

Two layers: a per-(username, client IP) counter that locks that pair out after
repeated failures, and a global failure rate cap so a spray across many
usernames is slowed down too. State is persisted so a container restart is not
a way to clear a lockout.
"""

from __future__ import annotations

import json
import os
import threading
import time

from .config import settings

MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
LOCKOUT_SECONDS = 15 * 60
GLOBAL_MAX_PER_MIN = 20
GLOBAL_COOLDOWN = 60

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}
_global_failures: list[float] = []
_global_until = 0.0


def _path() -> str:
	return os.path.join(settings.data_dir, "lockout.json")


def load() -> None:
	global _global_until
	try:
		with open(_path()) as fh:
			data = json.load(fh)
	except (OSError, ValueError):
		return
	with _lock:
		_failures.update({k: list(v) for k, v in data.get("failures", {}).items()})
		_locked_until.update(data.get("locked_until", {}))
		_global_until = data.get("global_until", 0.0)


def _save_locked() -> None:
	"""Persist current state. Caller must hold the lock."""
	try:
		os.makedirs(settings.data_dir, exist_ok=True)
		tmp = _path() + ".tmp"
		with open(tmp, "w") as fh:
			json.dump(
				{
					"failures": _failures,
					"locked_until": _locked_until,
					"global_until": _global_until,
				},
				fh,
			)
		os.replace(tmp, _path())
	except OSError as exc:
		print(f"[ops] WARNING: could not persist lockout state: {exc}", flush=True)


def check(username: str, client_ip: str) -> float:
	"""Return the number of seconds the caller must wait, 0 when allowed."""
	key = f"{username}@{client_ip}"
	now = time.time()
	with _lock:
		if _global_until > now:
			return _global_until - now
		until = _locked_until.get(key, 0.0)
		if until > now:
			return until - now
		if until:
			_locked_until.pop(key, None)
		return 0.0


def record_failure(username: str, client_ip: str) -> None:
	global _global_until
	key = f"{username}@{client_ip}"
	now = time.time()
	with _lock:
		hits = [t for t in _failures.get(key, []) if now - t < FAILURE_WINDOW]
		hits.append(now)
		_failures[key] = hits
		if len(hits) >= MAX_FAILURES:
			_locked_until[key] = now + LOCKOUT_SECONDS
			_failures[key] = []

		recent = [t for t in _global_failures if now - t < 60]
		recent.append(now)
		_global_failures[:] = recent
		if len(recent) >= GLOBAL_MAX_PER_MIN:
			_global_until = now + GLOBAL_COOLDOWN
			_global_failures.clear()

		_save_locked()


def record_success(username: str, client_ip: str) -> None:
	key = f"{username}@{client_ip}"
	with _lock:
		_failures.pop(key, None)
		_locked_until.pop(key, None)
		_save_locked()
