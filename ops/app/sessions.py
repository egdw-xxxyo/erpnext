"""In-process session store, each holding one SSH connection.

Deliberately not shared state: uvicorn runs with --workers 1 so a session is
always served by the process that owns its SSH connection.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from itsdangerous import BadSignature, TimestampSigner

from .config import settings
from .ssh import HostConnection

COOKIE_NAME = "ops_session"

_signer = TimestampSigner(settings.session_secret or "fake-host-secret", salt="ops-session")


@dataclass
class Session:
	sid: str
	username: str
	conn: HostConnection
	csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
	created: float = field(default_factory=time.time)
	last_used: float = field(default_factory=time.time)


_sessions: dict[str, Session] = {}
_lock = threading.Lock()


def create(username: str, conn: HostConnection) -> tuple[str, Session]:
	sid = secrets.token_urlsafe(32)
	session = Session(sid=sid, username=username, conn=conn)
	with _lock:
		_sessions[sid] = session
	return sign(sid), session


def sign(sid: str) -> str:
	return _signer.sign(sid.encode()).decode()


def get(cookie: str | None) -> Session | None:
	"""Resolve a signed cookie to a live session, or None."""
	if not cookie:
		return None
	try:
		sid = _signer.unsign(cookie, max_age=settings.session_ttl).decode()
	except BadSignature:
		return None

	with _lock:
		session = _sessions.get(sid)
		if session is None:
			return None
		now = time.time()
		expired = (
			now - session.created > settings.session_ttl or now - session.last_used > settings.session_idle
		)
		if expired or not session.conn.alive:
			_sessions.pop(sid, None)
			session.conn.close()
			return None
		session.last_used = now
		return session


def drop(cookie: str | None) -> None:
	if not cookie:
		return
	try:
		sid = _signer.unsign(cookie, max_age=settings.session_ttl).decode()
	except BadSignature:
		return
	with _lock:
		session = _sessions.pop(sid, None)
	if session:
		session.conn.close()


def reap() -> int:
	"""Drop expired or dead sessions, closing their SSH connections."""
	now = time.time()
	with _lock:
		dead = [
			sid
			for sid, s in _sessions.items()
			if now - s.created > settings.session_ttl
			or now - s.last_used > settings.session_idle
			or not s.conn.alive
		]
		victims = [_sessions.pop(sid) for sid in dead]
	for session in victims:
		session.conn.close()
	return len(victims)


def active_count() -> int:
	with _lock:
		return len(_sessions)


def any_live() -> Session | None:
	"""Any live session, used by background maintenance that needs a host
	connection. Returns None when nobody is logged in — maintenance simply
	waits, rather than the dashboard holding credentials of its own."""
	with _lock:
		for session in _sessions.values():
			if session.conn.alive:
				return session
	return None
