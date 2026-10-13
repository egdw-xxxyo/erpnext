"""Commands the dashboard may run through passwordless sudo on the host.

One list feeds both the Setup page (the sudoers text an admin pastes) and the
check panel, so the documentation can never drift from what is checked. Each
rule is an exact argv: no wildcards, because `apt-get *` or `du *` with a
writable option is a root shell.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass

from .ssh import HostConnection

SUDOERS_FILE = "/etc/sudoers.d/ops"


@dataclass(frozen=True)
class Rule:
	key: str
	argv: tuple[str, ...]
	used_by: str
	why: str


RULES: tuple[Rule, ...] = (
	Rule(
		"du",
		("/usr/bin/du",),
		"Space management → Space analysis",
		"Read-only. Lets the tree count directories the operator cannot read (/var/lib/docker).",
	),
	Rule(
		"ncdu",
		("/usr/bin/apt-get", "install", "-y", "ncdu"),
		"Space management → Install ncdu",
		"Installs the ncdu package. Exact arguments only.",
	),
	Rule(
		"journal",
		("/usr/bin/journalctl", "--vacuum-size=100M"),
		"Space management → Safe clean / Hard clean",
		"Trims the systemd journal to 100 MB.",
	),
)


def sudoers_text(user: str) -> str:
	lines = [f"# {SUDOERS_FILE} — managed by hand, read by the ops dashboard's Setup page"]
	lines += [f"{user} ALL=(root) NOPASSWD: {' '.join(r.argv)}" for r in RULES]
	return "\n".join(lines) + "\n"


def install_command(user: str) -> str:
	body = sudoers_text(user)
	return (
		f"sudo tee {SUDOERS_FILE} >/dev/null <<'EOF'\n{body}EOF\n"
		f"sudo chmod 440 {SUDOERS_FILE} && sudo visudo -cf {SUDOERS_FILE}"
	)


async def check(conn: HostConnection) -> list[dict]:
	"""`sudo -n -l <argv>` asks sudo whether it would allow the command; nothing runs."""

	def run() -> list[dict]:
		rows = []
		for rule in RULES:
			result = conn.run(f"sudo -n -l -- {shlex.join(rule.argv)} >/dev/null 2>&1", 15)
			rows.append({"rule": rule, "ok": result.rc == 0})
		return rows

	return await asyncio.to_thread(run)
