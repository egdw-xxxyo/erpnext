"""Encrypted-at-rest config for off-host FTP backup targets.

Split in two: a single shared **server** (host/port/username/password — one
FTP account, e.g. Tucha) and any number of named **targets** on that server
(just a name, an env label, and a remote path). Targets no longer carry their
own credentials — in practice every target we've ever configured sits on the
same account, and asking for host/port/user/password again for every named
path was pure friction. A target's `FtpTarget` is still assembled with the
server's creds merged in at read time, so `ftp.py` (which pushes/pulls/lists
over the SSH+curl path) is unchanged.

Every password never leaves this file in plaintext and is never echoed back
to a browser after it is saved — only a "configured since" marker is. It
reaches the monitored host only inside a short-lived netrc file written over
the SSH connection's stdin-piped script path (see ftp.py), never as part of
a job's command line.
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
class FtpServer:
	host: str
	port: int
	username: str
	password: str
	updated_at: float


@dataclass(frozen=True)
class FtpTargetMeta:
	"""What's actually stored per target — no credentials."""

	id: str
	name: str
	env_label: str  # one of ENV_LABELS
	remote_dir: str
	updated_at: float


@dataclass(frozen=True)
class FtpTarget:
	"""A target with the shared server's credentials merged in — the shape
	ftp.py expects to push/pull/test against."""

	id: str
	name: str
	env_label: str
	host: str
	port: int
	username: str
	password: str
	remote_dir: str
	updated_at: float


def _server_path() -> str:
	return os.path.join(settings.data_dir, "ftp_server.enc")


def _targets_path() -> str:
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


def _write_blob(path: str, data) -> None:
	blob = _fernet().encrypt(json.dumps(data).encode("utf-8"))
	os.makedirs(settings.data_dir, exist_ok=True)
	tmp = path + ".tmp"
	with open(tmp, "wb") as fh:
		fh.write(blob)
	os.chmod(tmp, 0o600)
	os.replace(tmp, path)


def _read_blob(path: str):
	with open(path, "rb") as fh:
		blob = fh.read()
	return json.loads(_fernet().decrypt(blob))


# ---- server ----------------------------------------------------------------


def get_server() -> FtpServer | None:
	try:
		raw = _read_blob(_server_path())
	except OSError:
		return _migrate_old_shape_targets()  # may populate the server file as a side effect
	except InvalidToken:
		print("[ops] WARNING: stored FTP server config could not be decrypted (key changed?)", flush=True)
		return None
	return FtpServer(**raw)


def save_server(*, host: str, port: int, username: str, password: str) -> FtpServer:
	existing = get_server()
	if not password:
		if existing is None:
			raise NotConfigured("password is required to configure the FTP server")
		password = existing.password
	server = FtpServer(
		host=host.strip(), port=port, username=username.strip(), password=password, updated_at=time.time()
	)
	_write_blob(_server_path(), asdict(server))
	return server


# ---- targets -----------------------------------------------------------------


def _migrate_old_shape_targets() -> FtpServer | None:
	"""One-shot: the pre-split ftp_targets.enc stored host/port/username/
	password on every row. Lift the first row's creds into the new server
	file, strip credentials from every row, rewrite in the new shape. Falls
	through to the even-older single-target ftp_config.enc if that file
	doesn't exist either."""
	try:
		raw = _read_blob(_targets_path())
	except OSError:
		return _migrate_legacy_single_target()
	except InvalidToken:
		print("[ops] WARNING: stored FTP targets could not be decrypted (key changed?)", flush=True)
		return None
	if not raw or "host" not in raw[0]:
		return None  # already new shape, or empty — nothing to migrate
	server = FtpServer(
		host=raw[0]["host"],
		port=raw[0]["port"],
		username=raw[0]["username"],
		password=raw[0]["password"],
		updated_at=time.time(),
	)
	_write_blob(_server_path(), asdict(server))
	trimmed = [
		FtpTargetMeta(
			id=row["id"],
			name=row["name"],
			env_label=row["env_label"],
			remote_dir=row["remote_dir"],
			updated_at=row.get("updated_at") or time.time(),
		)
		for row in raw
	]
	_write_blob(_targets_path(), [asdict(t) for t in trimmed])
	return server


def _migrate_legacy_single_target() -> FtpServer | None:
	"""One-shot import of the very first, single-target config format."""
	try:
		raw = _read_blob(_legacy_path())
	except OSError:
		return None
	except InvalidToken:
		return None
	server = FtpServer(
		host=raw["host"],
		port=raw["port"],
		username=raw["username"],
		password=raw["password"],
		updated_at=time.time(),
	)
	_write_blob(_server_path(), asdict(server))
	target = FtpTargetMeta(
		id=uuid.uuid4().hex,
		name="Migrated target",
		env_label=settings.env_label if settings.env_label in ENV_LABELS else "prod",
		remote_dir=raw["remote_dir"],
		updated_at=raw.get("updated_at") or time.time(),
	)
	_write_blob(_targets_path(), [asdict(target)])
	return server


def _list_target_meta() -> list[FtpTargetMeta]:
	try:
		raw = _read_blob(_targets_path())
	except OSError:
		_migrate_old_shape_targets()  # populates ftp_targets.enc as a side effect, if anything to migrate
		try:
			raw = _read_blob(_targets_path())
		except OSError:
			return []
	except InvalidToken:
		print("[ops] WARNING: stored FTP targets could not be decrypted (key changed?)", flush=True)
		return []
	if raw and "host" in raw[0]:
		_migrate_old_shape_targets()
		raw = _read_blob(_targets_path())
	return [FtpTargetMeta(**entry) for entry in raw]


def list_targets() -> list[FtpTarget]:
	"""Targets with the shared server's credentials merged in. Empty if no
	server is configured yet — a target with nowhere to connect is useless."""
	server = get_server()
	if server is None:
		return []
	return [
		FtpTarget(
			id=m.id,
			name=m.name,
			env_label=m.env_label,
			host=server.host,
			port=server.port,
			username=server.username,
			password=server.password,
			remote_dir=m.remote_dir,
			updated_at=m.updated_at,
		)
		for m in _list_target_meta()
	]


def get_target(target_id: str) -> FtpTarget | None:
	return next((t for t in list_targets() if t.id == target_id), None)


def save_target(*, target_id: str | None, name: str, env_label: str, remote_dir: str) -> FtpTargetMeta:
	metas = _list_target_meta()
	remote_dir = "/" + remote_dir.strip().strip("/")
	if target_id:
		existing = next((m for m in metas if m.id == target_id), None)
		if existing is None:
			raise NotConfigured(f"no such target: {target_id!r}")
		updated = replace(
			existing, name=name.strip(), env_label=env_label, remote_dir=remote_dir, updated_at=time.time()
		)
		metas = [updated if m.id == target_id else m for m in metas]
	else:
		updated = FtpTargetMeta(
			id=uuid.uuid4().hex,
			name=name.strip(),
			env_label=env_label,
			remote_dir=remote_dir,
			updated_at=time.time(),
		)
		metas = [*metas, updated]
	_write_blob(_targets_path(), [asdict(m) for m in metas])
	return updated


def delete_target(target_id: str) -> None:
	metas = [m for m in _list_target_meta() if m.id != target_id]
	_write_blob(_targets_path(), [asdict(m) for m in metas])


def require_target(target_id: str | None) -> FtpTarget:
	if not target_id:
		raise NotConfigured("no FTP backup target selected")
	target = get_target(target_id)
	if target is None:
		raise NotConfigured(f"FTP target {target_id!r} no longer exists — pick another one")
	return target
