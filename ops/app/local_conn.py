"""Local transport for developer setups with no sshd to talk to.

Same interface as ``ssh.HostConnection`` (``run``, ``run_in_repo``,
``open_stream``, ``alive``, ``close``, ``username``) so every route and the
job runner work unmodified — only ``auth.py`` decides which one to hand out,
based on ``settings.local_mode``.

Only meant for a developer's own machine: the ops container must have the
docker socket and the repo bind-mounted in for this to be useful at all (see
``docker-compose.ops.local.yml``), which is a real reduction in isolation
compared to the SSH path. Never enable ``OPS_LOCAL_MODE`` on a shared host.
"""

from __future__ import annotations

import os
import select
import shlex
import subprocess

from .config import settings


class Result:
	def __init__(self, rc: int, out: str, err: str):
		self.rc = rc
		self.out = out
		self.err = err

	@property
	def ok(self) -> bool:
		return self.rc == 0

	@property
	def text(self) -> str:
		return self.out.strip()


class _LocalChannel:
	"""Mimics the paramiko channel methods routes/jobs.py calls.

	paramiko's ``recv_ready()`` goes false once the remote side has closed and
	the local buffer is drained. A raw ``select()`` on a pipe doesn't: a pipe
	at EOF is always "ready" (the read that would return b"" is instant), so
	naively mirroring select() here would spin routes/jobs.py's stream loop
	forever after the process exits. ``_eof`` makes recv_ready() go false the
	call after the empty read, matching what that loop expects.
	"""

	def __init__(self, proc: subprocess.Popen):
		self._proc = proc
		self._fd = proc.stdout.fileno() if proc.stdout is not None else None
		self._eof = False

	def recv_ready(self) -> bool:
		if self._eof or self._fd is None:
			return False
		ready, _, _ = select.select([self._fd], [], [], 0)
		return bool(ready)

	def recv(self, n: int) -> bytes:
		if self._eof or self._fd is None:
			return b""
		data = os.read(self._fd, n)
		if not data:
			self._eof = True
		return data

	def exit_status_ready(self) -> bool:
		return self._proc.poll() is not None

	def close(self) -> None:
		if self._proc.poll() is None:
			self._proc.terminate()
		if self._proc.stdout is not None:
			self._proc.stdout.close()


class LocalConnection:
	"""Runs scripts as a subprocess in this container instead of over SSH."""

	def __init__(self, username: str):
		self.username = username

	def close(self) -> None:
		pass

	@property
	def alive(self) -> bool:
		return True

	def run(self, script: str, timeout: int = 30) -> Result:
		try:
			proc = subprocess.run(
				["bash", "-s"],
				input=script,
				capture_output=True,
				text=True,
				timeout=timeout,
			)
		except subprocess.TimeoutExpired as exc:
			return Result(rc=124, out=exc.stdout or "", err=(exc.stderr or "") + "\ntimed out")
		return Result(rc=proc.returncode, out=proc.stdout, err=proc.stderr)

	def run_in_repo(self, script: str, timeout: int = 30) -> Result:
		return self.run(f"cd {shlex.quote(settings.repo_path)} || exit 90\n{script}", timeout=timeout)

	def open_stream(self, command: str) -> _LocalChannel:
		proc = subprocess.Popen(
			["bash", "-c", command],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
		)
		return _LocalChannel(proc)


def connect(username: str) -> LocalConnection:
	"""No credentials to check — the caller (auth.py) already verified the
	username is in OPS_ALLOWED_USERS. Kept as a function, not a bare
	constructor call, to mirror ssh.connect()'s call shape."""
	return LocalConnection(username)
