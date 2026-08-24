"""SSH transport for the ops dashboard.

Every host interaction — reading stats, launching jobs, tailing logs — goes
through the SSH connection opened with the operator's own credentials at login.
There is no docker socket and no bind-mount, so the dashboard can never do more
on the host than the person logged into it could do by hand.

The password exists only for the duration of the ``connect()`` call. It is never
stored, so a dropped transport cannot be re-established silently: the session is
invalidated and the operator logs in again.
"""

from __future__ import annotations

import os
import shlex
import threading
from dataclasses import dataclass

import paramiko

from .config import settings


class AuthFailed(Exception):
	"""Credentials rejected by the host's sshd."""


class HostUnreachable(Exception):
	"""sshd could not be reached, or the host key was rejected."""


class SessionDead(Exception):
	"""The SSH transport is gone; the operator must log in again."""


@dataclass
class Result:
	rc: int
	out: str
	err: str

	@property
	def ok(self) -> bool:
		return self.rc == 0

	@property
	def text(self) -> str:
		return self.out.strip()


_known_hosts_lock = threading.Lock()


def _known_hosts_path() -> str:
	return os.path.join(settings.data_dir, "known_hosts")


def _load_host_keys(client: paramiko.SSHClient) -> bool:
	"""Load the pinned host keys. Returns True when a key is already pinned."""
	path = _known_hosts_path()
	if os.path.exists(path):
		client.load_host_keys(path)
		return bool(client.get_host_keys())
	return False


class HostConnection:
	"""One SSH connection, owned by one logged-in session.

	paramiko is not safe for concurrent use of a single ``SSHClient`` across
	threads, so every command takes the connection lock. Commands are short
	(long ones are detached on the host and only their log is tailed), so this
	does not serialise anything that matters.
	"""

	def __init__(self, client: paramiko.SSHClient, username: str):
		self._client = client
		self._lock = threading.Lock()
		self.username = username

	def close(self) -> None:
		try:
			self._client.close()
		except Exception:
			pass

	@property
	def alive(self) -> bool:
		transport = self._client.get_transport()
		return bool(transport and transport.is_active())

	def run(self, script: str, timeout: int = 30) -> Result:
		"""Run a bash script on the host and wait for it.

		The script is fed to ``bash -s`` on stdin rather than embedded in the
		command line, which sidesteps quoting entirely.
		"""
		if not self.alive:
			raise SessionDead("SSH transport is no longer active")
		with self._lock:
			try:
				stdin, stdout, stderr = self._client.exec_command("bash -s", timeout=timeout)
				stdin.write(script)
				stdin.channel.shutdown_write()
				out = stdout.read().decode("utf-8", "replace")
				err = stderr.read().decode("utf-8", "replace")
				rc = stdout.channel.recv_exit_status()
			except (paramiko.SSHException, OSError) as exc:
				raise SessionDead(str(exc)) from exc
		return Result(rc=rc, out=out, err=err)

	def run_in_repo(self, script: str, timeout: int = 30) -> Result:
		return self.run(f"cd {shlex.quote(settings.repo_path)} || exit 90\n{script}", timeout=timeout)

	def open_stream(self, command: str):
		"""Start a long-running command and return its channel file objects.

		Used for ``tail -f``. The caller must close the channel. Not guarded by
		the connection lock — a stream lives for minutes and would otherwise
		block every stat refresh — which is safe because paramiko multiplexes
		independent channels over one transport.
		"""
		if not self.alive:
			raise SessionDead("SSH transport is no longer active")
		transport = self._client.get_transport()
		channel = transport.open_session()
		channel.exec_command(command)
		return channel


def connect(username: str, password: str) -> HostConnection:
	"""Authenticate against the host's sshd. Raises AuthFailed / HostUnreachable."""
	client = paramiko.SSHClient()

	with _known_hosts_lock:
		pinned = _load_host_keys(client)
		# Trust on first use: the very first connection pins the key, every
		# later one is verified against it. AutoAddPolicy is never left on.
		client.set_missing_host_key_policy(
			paramiko.AutoAddPolicy() if not pinned else paramiko.RejectPolicy()
		)

		try:
			client.connect(
				hostname=settings.ssh_host,
				port=settings.ssh_port,
				username=username,
				password=password,
				allow_agent=False,
				look_for_keys=False,
				timeout=8,
				auth_timeout=8,
				banner_timeout=8,
			)
		except paramiko.AuthenticationException as exc:
			client.close()
			raise AuthFailed("invalid username or password") from exc
		except (paramiko.SSHException, OSError) as exc:
			client.close()
			raise HostUnreachable(f"cannot reach {settings.ssh_host}:{settings.ssh_port} — {exc}") from exc

		if not pinned:
			try:
				os.makedirs(settings.data_dir, exist_ok=True)
				client.save_host_keys(_known_hosts_path())
				key = client.get_transport().get_remote_server_key()
				print(
					f"[ops] pinned host key for {settings.ssh_host}: "
					f"{key.get_name()} {key.get_fingerprint().hex()}",
					flush=True,
				)
			except Exception as exc:  # pinning is best-effort; auth already succeeded
				print(f"[ops] WARNING: could not persist host key: {exc}", flush=True)

	transport = client.get_transport()
	if transport:
		transport.set_keepalive(30)
	return HostConnection(client, username)
