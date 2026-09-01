"""Off-host SFTP backup target: push, list, pull.

The configured password never becomes part of any command line (visible via
`ps` on the host for the lifetime of that process) or any log (job log, audit
log). It crosses the SSH channel exactly once per operation, as literal text
inside a heredoc in the script piped to `bash -s` on the host — the same
stdin-only path `HostConnection.run()` already uses for every host script,
never as a `bash -c` argv. That script relays the netrc content straight into
the backend container (which owns the backup files; the host has no bind
mount to them), where it is read by `curl --netrc-file` and then removed.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import time
import uuid

from . import jobs
from .config import settings
from .sftp_config import SftpConfig, require
from .ssh import HostConnection

_WRITE_NETRC_SCRIPT = """set -e
cd {repo} || exit 90
DC="docker compose -p {project} -f {repo}/docker-compose.yml"
NETRC="/tmp/ops-sftp-{token}.netrc"
$DC exec -T backend bash -c 'umask 077; cat > "$1"' _ "$NETRC" <<'{delim}'
machine {host}
login {username}
password {password}
{delim}
printf '%s' "$NETRC"
"""


def _write_netrc(conn: HostConnection, cfg: SftpConfig) -> str:
	"""Write a one-shot netrc file inside the backend container. Returns its
	container-local path. The caller is responsible for having the launched
	job (or this function's caller, on early failure) remove it."""
	token = uuid.uuid4().hex
	delim = f"OPS_NETRC_{uuid.uuid4().hex}"
	script = _WRITE_NETRC_SCRIPT.format(
		repo=shlex.quote(settings.repo_path),
		project=shlex.quote(settings.compose_project),
		token=token,
		delim=delim,
		host=cfg.host,
		username=cfg.username,
		password=cfg.password,
	)
	result = conn.run(script, timeout=20)
	if not result.ok or not result.text:
		raise RuntimeError(
			f"could not stage SFTP credentials on host: {result.err.strip() or result.out.strip()}"
		)
	return result.text.strip()


def push(conn: HostConnection, name: str, username: str) -> str:
	"""Launch a detached push job. Returns the job id."""
	cfg = require()
	netrc = _write_netrc(conn, cfg)
	command = (
		f"./deploy backup-push {shlex.quote(name)} {shlex.quote(cfg.host)} "
		f"{shlex.quote(str(cfg.port))} {shlex.quote(cfg.remote_dir)} {shlex.quote(netrc)}"
	)
	return jobs.launch(conn, "backup-push", command, f"Push backup {name}", username, {"name": name})


def pull(conn: HostConnection, name: str, username: str) -> str:
	cfg = require()
	netrc = _write_netrc(conn, cfg)
	command = (
		f"./deploy backup-pull {shlex.quote(name)} {shlex.quote(cfg.host)} "
		f"{shlex.quote(str(cfg.port))} {shlex.quote(cfg.remote_dir)} {shlex.quote(netrc)}"
	)
	return jobs.launch(conn, "backup-pull", command, f"Pull backup {name}", username, {"name": name})


def _list_remote_sync(conn: HostConnection) -> list[dict]:
	cfg = require()
	netrc = _write_netrc(conn, cfg)
	script = (
		f"cd {shlex.quote(settings.repo_path)} && "
		f"./deploy backup-remote-list {shlex.quote(cfg.host)} {shlex.quote(str(cfg.port))} "
		f"{shlex.quote(cfg.remote_dir)} {shlex.quote(netrc)}"
	)
	result = conn.run(script, timeout=60)
	try:
		entries = json.loads(result.text or "[]")
		return entries if isinstance(entries, list) else []
	except json.JSONDecodeError:
		raise RuntimeError(f"remote listing was not valid JSON: {result.out[:500]!r}") from None


REMOTE_TTL = 60.0


class RemoteBackupsCache:
	"""TTL'd, on-demand only — never part of the polled stats snapshot, since
	that would hit the third-party SFTP host every 10s for every open tab."""

	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._entries: list[dict] = []
		self._fetched_at = 0.0
		self._error: str | None = None

	async def get(self, conn: HostConnection, force: bool = False) -> dict:
		async with self._lock:
			fresh = self._entries and time.time() - self._fetched_at < REMOTE_TTL
			if not force and fresh:
				return self._snapshot()
			try:
				self._entries = await asyncio.to_thread(_list_remote_sync, conn)
				self._error = None
			except Exception as exc:
				self._error = str(exc)
			self._fetched_at = time.time()
			return self._snapshot()

	def _snapshot(self) -> dict:
		return {"entries": self._entries, "_fetched_at": self._fetched_at, "_error": self._error}


remote_cache = RemoteBackupsCache()
