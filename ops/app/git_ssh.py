"""Wraps a shell command with GIT_SSH_COMMAND pointed at a one-shot deploy
key staged on the host, when the calling ops user has one configured.

Mirrors ftp.py's netrc staging: the private key crosses the SSH channel only
via a stdin-piped script (never a command-line argv, never a log), lands in
a mode-600 temp file on the host, and is removed by a trap regardless of how
the wrapped command exits.
"""

from __future__ import annotations

import shlex
import uuid

from . import git_keys
from .ssh import HostConnection

_WRITE_KEY_SCRIPT = """set -e
KEYFILE="/tmp/ops-gitkey-{token}"
umask 077
cat > "$KEYFILE" <<'{delim}'
{key}
{delim}
chmod 600 "$KEYFILE"
printf '%s' "$KEYFILE"
"""


def _stage_key(conn: HostConnection, key: git_keys.GitKey) -> str | None:
	token = uuid.uuid4().hex
	delim = f"OPS_GITKEY_{uuid.uuid4().hex}"
	script = _WRITE_KEY_SCRIPT.format(token=token, delim=delim, key=key.private_key.rstrip("\n"))
	result = conn.run(script, timeout=20)
	if not result.ok or not result.text:
		return None
	return result.text.strip()


def wrap(conn: HostConnection, username: str, command: str) -> str:
	"""Returns `command` unchanged if the user has no key configured — the
	original git error is then whatever it already was, unmasked.

	This result gets embedded inside a single-quoted `bash -c '...'` body by
	jobs.launch() (see jobs.py's LAUNCH_SCRIPT), so — unlike everywhere else
	in this codebase — it must contain no single quote anywhere. `keyfile` is
	our own uuid4().hex path, so it is safe to double-quote without escaping.
	"""
	key = git_keys.load(username)
	if key is None:
		return command
	keyfile = _stage_key(conn, key)
	if keyfile is None or "'" in keyfile:
		return command
	ssh_cmd = f"ssh -i {keyfile} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
	return f'trap "rm -f {keyfile}" EXIT\nexport GIT_SSH_COMMAND="{ssh_cmd}"\n{command}'


def test_connection(conn: HostConnection, key: git_keys.GitKey) -> str:
	"""Synchronous — used by the "Test" button. `ssh -T git@github.com`
	always exits non-zero (GitHub refuses a shell), so success is judged by
	the greeting text, not the exit code."""
	keyfile = _stage_key(conn, key)
	if keyfile is None:
		raise RuntimeError("could not stage the key on the host")
	script = (
		f"trap 'rm -f {shlex.quote(keyfile)}' EXIT\n"
		f"ssh -i {shlex.quote(keyfile)} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "
		f"-o ConnectTimeout=10 -T git@github.com 2>&1 || true\n"
	)
	result = conn.run(script, timeout=20)
	output = (result.out or "").strip()
	if "successfully authenticated" not in output.lower():
		raise RuntimeError(output or "no response from github.com")
	return output
