"""Login throttling.

Two layers: a per-(username, client IP) counter that locks that pair out after
repeated failures, and a global failure rate cap so a spray across many
usernames is slowed down too. State is persisted in the ops database so a
container restart is not a way to clear a lockout.
"""

from __future__ import annotations

import threading
import time

from . import store

MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
LOCKOUT_SECONDS = 15 * 60
GLOBAL_MAX_PER_MIN = 20
GLOBAL_COOLDOWN = 60

GLOBAL_KEY = "lockout_global_until"

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}
_global_failures: list[float] = []
_global_until = 0.0


def load() -> None:
	"""Read persisted state into the in-process counters at startup."""
	global _global_until
	try:
		failures, locked_until = store.lockout_load()
		persisted_global = float(store.kv_get(GLOBAL_KEY, 0.0) or 0.0)
	except Exception as exc:
		print(f"[ops] WARNING: could not load lockout state: {exc}", flush=True)
		return
	with _lock:
		_failures.update(failures)
		_locked_until.update(locked_until)
		_global_until = persisted_global


def _persist_key_locked(key: str) -> None:
	"""Write one key's counters. Caller must hold the lock."""
	try:
		store.lockout_save(key, _failures.get(key, []), _locked_until.get(key, 0.0))
	except Exception as exc:
		print(f"[ops] WARNING: could not persist lockout state: {exc}", flush=True)


def _persist_global_locked() -> None:
	try:
		store.kv_set(GLOBAL_KEY, _global_until)
	except Exception as exc:
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
			_persist_key_locked(key)
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
			_persist_global_locked()

		_persist_key_locked(key)


def record_success(username: str, client_ip: str) -> None:
	key = f"{username}@{client_ip}"
	with _lock:
		_failures.pop(key, None)
		_locked_until.pop(key, None)
		try:
			store.lockout_forget(key)
		except Exception as exc:
			print(f"[ops] WARNING: could not persist lockout state: {exc}", flush=True)
