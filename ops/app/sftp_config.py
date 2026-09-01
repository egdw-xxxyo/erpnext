"""Encrypted-at-rest config for the off-host SFTP backup target.

One shared target per ops instance (matches the rest of ops' config: a single
host, a single environment). The password never leaves this file in plaintext
and is never echoed back to a browser after it is saved — only a "configured
since" marker is. It reaches the monitored host only inside a short-lived
netrc file written over the SSH connection's stdin-piped script path (see
sftp.py), never as part of a job's command line.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


class NotConfigured(Exception):
	pass


class MisconfiguredSecretKey(Exception):
	pass


@dataclass(frozen=True)
class SftpConfig:
	host: str
	port: int
	username: str
	password: str
	remote_dir: str
	updated_at: float


def _path() -> str:
	return os.path.join(settings.data_dir, "sftp_config.enc")


def _fernet() -> Fernet:
	if not settings.secret_key:
		raise MisconfiguredSecretKey(
			"OPS_SECRET_KEY is required to store the SFTP target. Generate one with: openssl rand -hex 32"
		)
	# Fernet wants 32 url-safe-base64 bytes; derive them from whatever length
	# key the operator generated the same way OPS_SESSION_SECRET is generated.
	key = base64.urlsafe_b64encode(settings.secret_key.encode("utf-8").ljust(32, b"0")[:32])
	return Fernet(key)


def load() -> SftpConfig | None:
	try:
		with open(_path(), "rb") as fh:
			blob = fh.read()
	except OSError:
		return None
	try:
		raw = _fernet().decrypt(blob)
	except InvalidToken:
		print("[ops] WARNING: stored SFTP config could not be decrypted (key changed?)", flush=True)
		return None
	return SftpConfig(**json.loads(raw))


def save(*, host: str, port: int, username: str, password: str, remote_dir: str) -> None:
	config = SftpConfig(
		host=host.strip(),
		port=port,
		username=username.strip(),
		password=password,
		remote_dir="/" + remote_dir.strip().strip("/"),
		updated_at=time.time(),
	)
	blob = _fernet().encrypt(json.dumps(asdict(config)).encode("utf-8"))
	os.makedirs(settings.data_dir, exist_ok=True)
	tmp = _path() + ".tmp"
	with open(tmp, "wb") as fh:
		fh.write(blob)
	os.chmod(tmp, 0o600)
	os.replace(tmp, _path())


def require() -> SftpConfig:
	config = load()
	if config is None:
		raise NotConfigured("no SFTP backup target configured yet — set one under Settings")
	return config
