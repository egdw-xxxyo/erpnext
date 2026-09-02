"""Off-host FTP backup targets: push, list, pull. Multi-target — see
ftp_config.py for why (dev pulling a prod backup down for local testing).

The configured password never becomes part of any command line (visible via
`ps` on the host for the lifetime of that process) or any log (job log, audit
log). It crosses the SSH channel exactly once per operation, as literal text
inside a heredoc in the script piped to `bash -s` on the host — the same
stdin-only path `HostConnection.run()` already uses for every host script,
never as a `bash -c` argv. That script relays the netrc content straight into
the backend container (which owns the backup files; the host has no bind
mount to them), where it is read by `curl --netrc-file` and then removed.

test_connection() is the one exception: it touches no backup files, so it
stages its netrc on the host's own /tmp instead (_write_netrc_host) and runs
curl there directly — no dependency on the backend container being up just
to check whether a set of FTP credentials works.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import time
import uuid

from . import jobs
from .config import settings
from .ftp_config import FtpTarget, require_target
from .ssh import HostConnection

_WRITE_NETRC_SCRIPT = """set -e
cd {repo} || exit 90
DC="docker compose -p {project} -f {repo}/docker-compose.yml"
NETRC="/tmp/ops-ftp-{token}.netrc"
$DC exec -T backend bash -c 'umask 077; cat > "$1"' _ "$NETRC" <<'{delim}'
machine {host}
login {username}
password {password}
{delim}
printf '%s' "$NETRC"
"""


def _write_netrc(conn: HostConnection, target: FtpTarget) -> str:
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
		host=target.host,
		username=target.username,
		password=target.password,
	)
	result = conn.run(script, timeout=20)
	if not result.ok or not result.text:
		raise RuntimeError(
			f"could not stage FTP credentials on host: {result.err.strip() or result.out.strip()}"
		)
	return result.text.strip()


def push(conn: HostConnection, name: str, username: str, target_id: str) -> str:
	"""Launch a detached push job. Returns the job id."""
	target = require_target(target_id)
	netrc = _write_netrc(conn, target)
	command = (
		f"./deploy backup-push {shlex.quote(name)} {shlex.quote(target.host)} "
		f"{shlex.quote(str(target.port))} {shlex.quote(target.remote_dir)} {shlex.quote(netrc)}"
	)
	return jobs.launch(
		conn,
		"backup-push",
		command,
		f"Push backup {name} to {target.name}",
		username,
		{"name": name, "target": target.name},
	)


def pull(conn: HostConnection, name: str, username: str, target_id: str) -> str:
	target = require_target(target_id)
	netrc = _write_netrc(conn, target)
	command = (
		f"./deploy backup-pull {shlex.quote(name)} {shlex.quote(target.host)} "
		f"{shlex.quote(str(target.port))} {shlex.quote(target.remote_dir)} {shlex.quote(netrc)}"
	)
	return jobs.launch(
		conn,
		"backup-pull",
		command,
		f"Pull backup {name} from {target.name}",
		username,
		{"name": name, "target": target.name},
	)


_WRITE_NETRC_HOST_SCRIPT = """set -e
NETRC="/tmp/ops-ftp-{token}.netrc"
umask 077
cat > "$NETRC" <<'{delim}'
machine {host}
login {username}
password {password}
{delim}
printf '%s' "$NETRC"
"""


def _write_netrc_host(conn: HostConnection, target: FtpTarget) -> str:
	"""Same idea as _write_netrc, but on the host's own /tmp instead of inside
	the backend container. Used only by test_connection: a connection test
	touches no backup files, so it has no reason to depend on the backend
	container being up at all — unlike push/pull/list, which stage the netrc
	inside backend because that's where the backup files (and the only curl
	binary) already live."""
	token = uuid.uuid4().hex
	delim = f"OPS_NETRC_{uuid.uuid4().hex}"
	script = _WRITE_NETRC_HOST_SCRIPT.format(
		token=token,
		delim=delim,
		host=target.host,
		username=target.username,
		password=target.password,
	)
	result = conn.run(script, timeout=20)
	if not result.ok or not result.text:
		raise RuntimeError(
			f"could not stage FTP credentials on host: {result.err.strip() or result.out.strip()}"
		)
	return result.text.strip()


def test_connection(conn: HostConnection, target: FtpTarget) -> list[str]:
	"""Synchronous — used by the "Test connection" button, which waits on it.
	Lists the target's root/remote_dir so success is visibly provable, not
	just a green checkmark."""
	netrc = _write_netrc_host(conn, target)
	script = (
		f"trap 'rm -f {shlex.quote(netrc)}' EXIT\n"
		f"cd {shlex.quote(settings.repo_path)} && "
		f"./deploy backup-remote-test {shlex.quote(target.host)} {shlex.quote(str(target.port))} "
		f"{shlex.quote(target.remote_dir)} {shlex.quote(netrc)}"
	)
	result = conn.run(script, timeout=20)
	if not result.ok:
		raise RuntimeError(result.err.strip() or result.out.strip() or "connection test failed")
	return _parse_listing(result.out)


def _parse_listing(text: str) -> list[str]:
	"""curl's FTP directory listing is `ls -l`-style lines; the name is
	whatever comes after the 8th field. Names containing spaces are not
	representable this way — good enough for a connectivity check, not a
	general-purpose listing."""
	names = []
	for line in text.splitlines():
		parts = line.split(maxsplit=8)
		if len(parts) < 9:
			continue
		name = parts[8]
		if name in (".", ".."):
			continue
		names.append(name)
	return names


def _list_remote_sync(conn: HostConnection, target: FtpTarget) -> list[dict]:
	netrc = _write_netrc(conn, target)
	script = (
		f"cd {shlex.quote(settings.repo_path)} && "
		f"./deploy backup-remote-list {shlex.quote(target.host)} {shlex.quote(str(target.port))} "
		f"{shlex.quote(target.remote_dir)} {shlex.quote(netrc)}"
	)
	result = conn.run(script, timeout=60)
	try:
		entries = json.loads(result.text or "[]")
		return entries if isinstance(entries, list) else []
	except json.JSONDecodeError:
		raise RuntimeError(f"remote listing was not valid JSON: {result.out[:500]!r}") from None


REMOTE_TTL = 60.0


class RemoteBackupsCache:
	"""TTL'd, on-demand only, keyed by target id — never part of the polled
	stats snapshot, since that would hit every configured FTP host every 10s
	for every open tab."""

	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._by_target: dict[str, dict] = {}

	async def get(self, conn: HostConnection, target_id: str, force: bool = False) -> dict:
		async with self._lock:
			entry = self._by_target.get(target_id, {"entries": [], "_fetched_at": 0.0, "_error": None})
			fresh = entry["entries"] and time.time() - entry["_fetched_at"] < REMOTE_TTL
			if not force and fresh:
				return dict(entry)
			try:
				target = require_target(target_id)
				entries = await asyncio.to_thread(_list_remote_sync, conn, target)
				entry = {"entries": entries, "_error": None}
			except Exception as exc:
				entry = {"entries": entry.get("entries", []), "_error": str(exc)}
			entry["_fetched_at"] = time.time()
			self._by_target[target_id] = entry
			return dict(entry)


remote_cache = RemoteBackupsCache()
