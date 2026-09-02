"""Per-ops-user SSH deploy key for git operations against GitHub on the
monitored host.

`./updateRepo`'s `git pull origin` needs to authenticate to github.com, and
the host's own ambient git credentials may not be set up for a non-
interactive session (no TTY to prompt on, no keychain to unlock) — that is
what surfaces as "could not read Username for 'https://github.com'" in a
job's log. Rather than one shared deploy key for the whole dashboard, each
ops user stores their own (matches how GitHub keys are normally issued
per-person). Stored the same way as an FTP target's password: encrypted at
rest, write-only after save, never echoed back to a browser.

Only helps when the host's `origin` remote is an SSH URL
(`git@github.com:...`) — GIT_SSH_COMMAND has no effect on an `https://`
remote. That is a one-time `git remote set-url origin git@github.com:...`
on the host, done once by an operator with shell access; this module does
not touch remote URLs itself.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


class MisconfiguredSecretKey(Exception):
	pass


@dataclass(frozen=True)
class GitKey:
	username: str
	private_key: str
	updated_at: float


def _safe_username(username: str) -> str:
	return "".join(c for c in username if c.isalnum() or c in "-_.") or "user"


def _path(username: str) -> str:
	return os.path.join(settings.data_dir, f"git_key_{_safe_username(username)}.enc")


def _fernet() -> Fernet:
	if not settings.secret_key:
		raise MisconfiguredSecretKey(
			"OPS_SECRET_KEY is required to store a git SSH key. Generate one with: openssl rand -hex 32"
		)
	key = base64.urlsafe_b64encode(settings.secret_key.encode("utf-8").ljust(32, b"0")[:32])
	return Fernet(key)


def load(username: str) -> GitKey | None:
	try:
		with open(_path(username), "rb") as fh:
			blob = fh.read()
	except OSError:
		return None
	try:
		raw = json.loads(_fernet().decrypt(blob))
	except InvalidToken:
		print(f"[ops] WARNING: stored git key for {username!r} could not be decrypted (key changed?)", flush=True)
		return None
	return GitKey(**raw)


def save(username: str, private_key: str) -> None:
	key = GitKey(username=username, private_key=private_key.strip() + "\n", updated_at=time.time())
	blob = _fernet().encrypt(json.dumps(asdict(key)).encode("utf-8"))
	os.makedirs(settings.data_dir, exist_ok=True)
	path = _path(username)
	tmp = path + ".tmp"
	with open(tmp, "wb") as fh:
		fh.write(blob)
	os.chmod(tmp, 0o600)
	os.replace(tmp, path)


def delete(username: str) -> None:
	try:
		os.remove(_path(username))
	except OSError:
		pass
