"""The complete set of things the dashboard is allowed to run on the host.

The HTTP layer never accepts a shell string. Every action is an entry here with
a fixed argv template and a validator per parameter; anything that does not
match is a 400. This is the single control that stops the dashboard from being
a remote shell wearing a login form.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field

from . import prefs

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
BACKUP_RE = re.compile(r"^[0-9]{8}_[0-9]{6}-[A-Za-z0-9_.-]{1,64}$")


class InvalidArgument(ValueError):
	pass


def _branch(value: str) -> str:
	value = (value or "").strip()
	if not BRANCH_RE.match(value) or ".." in value:
		raise InvalidArgument(f"invalid branch name: {value!r}")
	return value


def _backup_name(value: str) -> str:
	value = (value or "").strip()
	if not BACKUP_RE.match(value):
		raise InvalidArgument(f"invalid backup name: {value!r}")
	return value


@dataclass(frozen=True)
class Command:
	key: str
	label: str
	description: str
	# Builds the shell line. Receives already-validated, already-quoted params.
	build: Callable[[dict], str]
	params: dict[str, Callable[[str], str]] = field(default_factory=dict)
	destructive: bool = False
	# Refuse to start when the working tree has uncommitted changes.
	needs_clean_tree: bool = False
	confirm_phrase: str | None = None

	def render(self, raw: dict) -> tuple[str, dict]:
		values = {}
		for name, validator in self.params.items():
			values[name] = validator(raw.get(name, ""))
		return self.build({k: shlex.quote(v) for k, v in values.items()}), values


COMMANDS: dict[str, Command] = {
	"update-repo": Command(
		key="update-repo",
		label="Update repo",
		description="git pull + fetch tags + submodule sync (./updateRepo). Does not rebuild.",
		build=lambda _: "./updateRepo",
	),
	"build": Command(
		key="build",
		label="Deploy (build)",
		description="Rebuild the image and run the full deploy (./deploy build --silent).",
		# One job, one shell line: when the "safety backup" preference is on,
		# a failed backup (disk full, etc.) short-circuits via && and the
		# build never runs — a hard gate, in the same spirit as
		# backup_space_guard already blocking backup itself. --no-files keeps
		# it fast enough to run before every deploy, not just occasionally.
		build=lambda _: (
			"./deploy backup --no-files && ./deploy build --silent"
			if prefs.get("pre_deploy_backup", True)
			else "./deploy build --silent"
		),
		destructive=True,
	),
	"backup": Command(
		key="backup",
		label="Backup",
		description="bench backup with files, pruning to the retention limit.",
		build=lambda p: f"./deploy backup {p['mode']}",
		params={"mode": lambda v: "--no-files" if v == "no-files" else "--with-files"},
	),
	"restore": Command(
		key="restore",
		label="Restore",
		description="Destroys the current database and files, replacing them with a backup.",
		build=lambda p: f"./deploy restore {p['name']} --yes",
		params={"name": _backup_name},
		destructive=True,
		confirm_phrase="site",
	),
	"backup-remove": Command(
		key="backup-remove",
		label="Remove backup",
		description="Permanently deletes one local backup set. Does not touch any off-host copy.",
		build=lambda p: f"./deploy backup-remove {p['name']}",
		params={"name": _backup_name},
		destructive=True,
		confirm_phrase="site",
	),
	"backup-clean": Command(
		key="backup-clean",
		label="Clean old backups",
		description="Deletes every local backup except the most recent one.",
		build=lambda _: "./deploy backup --prune-only --keep=1",
		destructive=True,
		confirm_phrase="site",
	),
	"space-clean": Command(
		key="space-clean",
		label="Safe clean",
		description=(
			"Prunes dangling Docker images and unused build cache, vacuums the systemd journal to "
			"100 MB. Never touches backups, the site database, or files inside sites/."
		),
		build=lambda _: "./deploy space-clean",
	),
	"space-hard-clean": Command(
		key="space-hard-clean",
		label="Hard clean",
		description=(
			"Removes every Docker image and build cache layer not in active use, including the "
			'previous release\'s tagged image — matches the full "Reclaimable" number shown per '
			"row. Rollback to the previous image is no longer possible after this runs, and the "
			"next build starts uncached (slower). Never touches backups, the site database, or "
			"files inside sites/."
		),
		build=lambda _: "./deploy space-hard-clean",
		destructive=True,
		confirm_phrase="site",
	),
	"switch-branch": Command(
		key="switch-branch",
		label="Switch branch",
		description="Checkout another branch and pull. Does not rebuild — run a deploy after.",
		build=lambda p: f"git fetch --all --tags --prune && git checkout {p['branch']} && ./updateRepo",
		params={"branch": _branch},
		destructive=True,
		needs_clean_tree=True,
	),
	"ops-rebuild": Command(
		key="ops-rebuild",
		label="Rebuild dashboard",
		description="Rebuild and restart this dashboard (./deploy ops rebuild).",
		build=lambda _: "./deploy ops rebuild",
	),
}


def validate_backup_name(value: str) -> str:
	return _backup_name(value)


def get(key: str) -> Command:
	command = COMMANDS.get(key)
	if command is None:
		raise InvalidArgument(f"unknown action: {key!r}")
	return command
