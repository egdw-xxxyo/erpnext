"""Encrypted-at-rest config for off-host FTP backup targets.

Multiple named targets, each tagged with the environment (prod/dev/test) it
belongs to — lets a dev instance configure prod's target read-only-in-intent
(pull a prod backup down for local testing) without touching what dev itself
pushes to. Every password never leaves this file in plaintext and is never
echoed back to a browser after it is saved — only a "configured since"
marker is. It reaches the monitored host only inside a short-lived netrc file
written over the SSH connection's stdin-piped script path (see ftp.py), never
as part of a job's command line.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, replace

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

ENV_LABELS = ("prod", "dev", "test")


class NotConfigured(Exception):
	pass


class MisconfiguredSecretKey(Exception):
	pass


@dataclass(frozen=True)
class FtpTarget:
	id: str
	name: str
	env_label: str  # one of ENV_LABELS
	host: str
	port: int
	username: str
	password: str
	remote_dir: str
	updated_at: float


def _path() -> str:
	return os.path.join(settings.data_dir, "ftp_targets.enc")


def _legacy_path() -> str:
	return os.path.join(settings.data_dir, "ftp_config.enc")


def _fernet() -> Fernet:
	if not settings.secret_key:
		raise MisconfiguredSecretKey(
			"OPS_SECRET_KEY is required to store an FTP target. Generate one with: openssl rand -hex 32"
		)
	# Fernet wants 32 url-safe-base64 bytes; derive them from whatever length
	# key the operator generated the same way OPS_SESSION_SECRET is generated.
	key = base64.urlsafe_b64encode(settings.secret_key.encode("utf-8").ljust(32, b"0")[:32])
	return Fernet(key)


def _write(targets: list[FtpTarget]) -> None:
	blob = _fernet().encrypt(json.dumps([asdict(t) for t in targets]).encode("utf-8"))
	os.makedirs(settings.data_dir, exist_ok=True)
	tmp = _path() + ".tmp"
	with open(tmp, "wb") as fh:
		fh.write(blob)
	os.chmod(tmp, 0o600)
	os.replace(tmp, _path())


def _migrate_legacy() -> list[FtpTarget] | None:
	"""One-shot import of the single pre-multi-target FTP config, if present
	and no new-format file has been written yet. Env label is guessed as this
	host's own — the operator can fix it under Configuration."""
	try:
		with open(_legacy_path(), "rb") as fh:
			blob = fh.read()
	except OSError:
		return None
	try:
		raw = json.loads(_fernet().decrypt(blob))
	except InvalidToken:
		return None
	target = FtpTarget(
		id=uuid.uuid4().hex,
		name="Migrated target",
		env_label=settings.env_label if settings.env_label in ENV_LABELS else "prod",
		host=raw["host"],
		port=raw["port"],
		username=raw["username"],
		password=raw["password"],
		remote_dir=raw["remote_dir"],
		updated_at=raw.get("updated_at") or time.time(),
	)
	_write([target])
	return [target]


def list_targets() -> list[FtpTarget]:
	try:
		with open(_path(), "rb") as fh:
			blob = fh.read()
	except OSError:
		return _migrate_legacy() or []
	try:
		raw = json.loads(_fernet().decrypt(blob))
	except InvalidToken:
		print("[ops] WARNING: stored FTP targets could not be decrypted (key changed?)", flush=True)
		return []
	return [FtpTarget(**entry) for entry in raw]


def get_target(target_id: str) -> FtpTarget | None:
	return next((t for t in list_targets() if t.id == target_id), None)


def save_target(
	*,
	target_id: str | None,
	name: str,
	env_label: str,
	host: str,
	port: int,
	username: str,
	password: str,
	remote_dir: str,
) -> FtpTarget:
	targets = list_targets()
	remote_dir = "/" + remote_dir.strip().strip("/")
	if target_id:
		existing = next((t for t in targets if t.id == target_id), None)
		if existing is None:
			raise NotConfigured(f"no such target: {target_id!r}")
		updated = replace(
			existing,
			name=name.strip(),
			env_label=env_label,
			host=host.strip(),
			port=port,
			username=username.strip(),
			password=password or existing.password,
			remote_dir=remote_dir,
			updated_at=time.time(),
		)
		targets = [updated if t.id == target_id else t for t in targets]
	else:
		updated = FtpTarget(
			id=uuid.uuid4().hex,
			name=name.strip(),
			env_label=env_label,
			host=host.strip(),
			port=port,
			username=username.strip(),
			password=password,
			remote_dir=remote_dir,
			updated_at=time.time(),
		)
		targets = [*targets, updated]
	_write(targets)
	return updated


def delete_target(target_id: str) -> None:
	targets = [t for t in list_targets() if t.id != target_id]
	_write(targets)


def require_target(target_id: str | None) -> FtpTarget:
	if not target_id:
		raise NotConfigured("no FTP backup target selected")
	target = get_target(target_id)
	if target is None:
		raise NotConfigured(f"FTP target {target_id!r} no longer exists — pick another one")
	return target
