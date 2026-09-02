"""The scheduled off-host backup, expressed as a marked line in the operator's
own crontab on the host — not an in-process scheduler.

ops has no way to authenticate unattended at 3am without either storing a new
login credential (breaking the "no stored SSH password" rule this whole app
is built around) or piggybacking on a session that may not be open at the
scheduled time. Host cron sidesteps both: it is already there, already runs
as the operator's own OS account, and needs nothing new stored. Installing or
removing the line still only happens while an operator is logged in — this
module just edits crontab over that session's existing SSH connection, the
same way every other action here touches the host.

`./deploy backup-scheduled` (the cron target) is what actually fetches the
FTP credentials, from the running ops container, at trigger time.
"""

from __future__ import annotations

import shlex

from .ssh import HostConnection

MARKER = "ops-scheduled-backup"


class ScheduleError(Exception):
	pass


def read(conn: HostConnection) -> dict | None:
	result = conn.run(f"crontab -l 2>/dev/null | grep -F '# {MARKER}' || true", timeout=10)
	line = result.text.strip()
	if not line:
		return None
	parts = line.split()
	if len(parts) < 5:
		return None
	minute, hour, _, _, dow = parts[0:5]
	try:
		return {
			"time": f"{int(hour):02d}:{int(minute):02d}",
			"frequency": "daily" if dow == "*" else "weekly",
			"weekday": None if dow == "*" else int(dow),
		}
	except ValueError:
		return None


# `crontab -l` exits non-zero both when there genuinely is no crontab yet
# (fine, start from empty) and on a real read failure (must NOT proceed, or
# `crontab -` below would silently replace the whole file — including any
# entries this app never wrote — with just our one line).
_READ_EXISTING = """
if existing=$(crontab -l 2>&1); then
  :
else
  case "$existing" in
    *"no crontab"*) existing="" ;;
    *) echo "ERROR: could not read existing crontab: $existing" >&2; exit 1 ;;
  esac
fi
"""


def _apply(conn: HostConnection, extra_line: str | None) -> None:
	append = f"printf '%s\\n' {shlex.quote(extra_line)} >> \"$f\"\n" if extra_line else ""
	script = (
		_READ_EXISTING
		+ f"""
f=$(mktemp)
if [ -n "$existing" ]; then
  printf '%s\\n' "$existing" | grep -vF '# {MARKER}' > "$f" || true
fi
{append}crontab "$f"
rm -f "$f"
"""
	)
	result = conn.run(script, timeout=15)
	if not result.ok:
		raise ScheduleError(result.err.strip() or "crontab update failed")


def write(conn: HostConnection, *, frequency: str, weekday: int, time_str: str, repo_path: str) -> None:
	hour_str, minute_str = time_str.split(":")
	hour, minute = int(hour_str), int(minute_str)
	dow = "*" if frequency == "daily" else str(int(weekday))
	line = (
		f"{minute} {hour} * * {dow} cd {shlex.quote(repo_path)} && mkdir -p .ops-jobs && "
		f"./deploy backup-scheduled >> .ops-jobs/cron-backup.log 2>&1 # {MARKER}"
	)
	_apply(conn, line)


def remove(conn: HostConnection) -> None:
	_apply(conn, None)
