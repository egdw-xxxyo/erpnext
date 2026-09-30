"""The standby mirror's config: ``.mirror.env`` in the repo on the host.

./deploy sources that file (tools/mirror.sh); this module is only a typed
editor for it. Runbook: docs/mirror-standby.md.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

ENV_FILE = ".mirror.env"
KEY_FILE = "~/.ssh/erp_mirror"

ROLES = {"primary": "Main server", "replica": "Standby mirror"}

_USER_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
# Lands inside SQL string literals in tools/mirror.sh: no quotes, backslashes or spaces.
_PASSWORD_RE = re.compile(r"^[A-Za-z0-9._@%+=:,!#^*()\[\]{}-]{8,64}$")
_SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}@[A-Za-z0-9.-]{1,253}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,255}$")


class InvalidMirrorConfig(ValueError):
	pass


@dataclass(frozen=True)
class Field:
	key: str
	label: str
	help: str
	roles: tuple[str, ...]
	default: str = ""
	secret: bool = False


FIELDS: tuple[Field, ...] = (
	Field(
		"MIRROR_PRIMARY_DB_PORT",
		"Main's database port (loopback only)",
		"Main publishes MariaDB on 127.0.0.1 at this port; the mirror reaches it through SSH.",
		("primary", "replica"),
		"3307",
	),
	Field("MIRROR_REPL_USER", "Replication user", "", ("primary", "replica"), "repl"),
	Field(
		"MIRROR_REPL_PASSWORD",
		"Replication password",
		"Same on both hosts. 8+ characters, no quotes, backslashes or spaces.",
		("primary", "replica"),
		secret=True,
	),
	Field("MIRROR_PRIMARY_SSH", "Main server SSH login", "user@host", ("replica",)),
	Field(
		"MIRROR_PRIMARY_SSH_KEY",
		"SSH private key on this host",
		"Absolute path. Use 'Generate key' to create one.",
		("replica",),
	),
	Field(
		"MIRROR_PRIMARY_REPO", "Repo path on main", "Where ./deploy lives on the main server.", ("replica",)
	),
	Field("MIRROR_FILES_INTERVAL", "Attachment sync interval, seconds", "", ("replica",), "300"),
)
FIELD_KEYS = {f.key for f in FIELDS}


def parse(text: str | None) -> dict[str, str]:
	values: dict[str, str] = {}
	for raw in (text or "").splitlines():
		line = raw.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, _, value = line.partition("=")
		try:
			parts = shlex.split(value, comments=True)
		except ValueError:
			parts = [value]
		values[key.strip()] = parts[0] if parts else ""
	return values


def render(values: dict[str, str]) -> str:
	lines = [
		"# Standby mirror config — edited by the ops dashboard (Configuration page).",
		"# Runbook: docs/mirror-standby.md",
	]
	role = values.get("MIRROR_ROLE", "")
	if role:
		lines.append(f"MIRROR_ROLE={role}")
	else:
		lines.append("# Mirror disabled; settings below are kept for when it is enabled again.")
	for field in FIELDS:
		value = values.get(field.key, "")
		if value:
			lines.append(f"{field.key}={shlex.quote(value)}")
	for key, value in values.items():
		if key != "MIRROR_ROLE" and key not in FIELD_KEYS and value:
			lines.append(f"{key}={shlex.quote(value)}")
	return "\n".join(lines) + "\n"


def _int(value: str, label: str, low: int, high: int) -> str:
	try:
		number = int(value)
	except ValueError as exc:
		raise InvalidMirrorConfig(f"{label} must be a number.") from exc
	if not low <= number <= high:
		raise InvalidMirrorConfig(f"{label} must be between {low} and {high}.")
	return str(number)


def validate(current: dict[str, str], form: dict[str, str]) -> dict[str, str]:
	"""Merge the submitted form over the current values and check them.

	A blank password keeps the stored one. Fields of the other role are kept
	as they are, so switching the role back loses nothing.
	"""
	values = dict(current)
	enabled = form.get("enabled") == "on"
	role = (form.get("role") or "").strip()
	if enabled and role not in ROLES:
		raise InvalidMirrorConfig("Pick whether this host is the main server or the standby mirror.")
	values["MIRROR_ROLE"] = role if enabled else ""

	for field in FIELDS:
		if field.key not in form:
			continue
		value = (form.get(field.key) or "").strip()
		if field.secret and not value:
			continue
		values[field.key] = value

	if not enabled:
		return values

	for field in FIELDS:
		if role in field.roles and not values.get(field.key):
			if field.default:
				values[field.key] = field.default
			else:
				raise InvalidMirrorConfig(f"{field.label} is required.")

	values["MIRROR_PRIMARY_DB_PORT"] = _int(values["MIRROR_PRIMARY_DB_PORT"], "Database port", 1024, 65535)
	if not _USER_RE.match(values["MIRROR_REPL_USER"]):
		raise InvalidMirrorConfig("Replication user: letters, digits and _ only.")
	if not _PASSWORD_RE.match(values["MIRROR_REPL_PASSWORD"]):
		raise InvalidMirrorConfig("Replication password: 8-64 characters, no quotes, backslashes or spaces.")
	if role == "replica":
		if not _SSH_TARGET_RE.match(values["MIRROR_PRIMARY_SSH"]):
			raise InvalidMirrorConfig("Main server SSH login must look like user@host.")
		for key, label in (("MIRROR_PRIMARY_SSH_KEY", "SSH key path"), ("MIRROR_PRIMARY_REPO", "Repo path")):
			if not _PATH_RE.match(values[key]):
				raise InvalidMirrorConfig(f"{label} must be an absolute path.")
		values["MIRROR_FILES_INTERVAL"] = _int(values["MIRROR_FILES_INTERVAL"], "Sync interval", 30, 86400)
	return values
