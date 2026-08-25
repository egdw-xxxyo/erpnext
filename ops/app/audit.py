"""Append-only audit trail, written on the host as the authenticated operator.

Writing it through the operator's own SSH session means file ownership
corroborates the recorded username — the dashboard cannot forge a line as
somebody else, because it has no credentials of its own.
"""

from __future__ import annotations

import json
import shlex
import time

from .config import settings
from .ssh import HostConnection

AUDIT_FILE = ".ops-jobs/audit.log"


def _line(**fields) -> str:
	fields.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
	return json.dumps(fields, ensure_ascii=False, sort_keys=True)


def write(conn: HostConnection, **fields) -> None:
	"""Append one JSONL record. Never raises — a failed audit write must not
	break the action the operator asked for, but it is loud in the app log."""
	jobs_dir = shlex.quote(settings.jobs_dir)
	path = shlex.quote(f"{settings.repo_path}/{AUDIT_FILE}")
	lock = shlex.quote(f"{settings.jobs_dir}/.audit.lock")
	payload = shlex.quote(_line(**fields))
	# The lock is held by this script's fd 9 and released when it exits, so
	# concurrent writers cannot interleave a partial line.
	script = f"mkdir -p {jobs_dir}\n" f"exec 9>>{lock}\n" "flock 9\n" f"printf '%s\\n' {payload} >> {path}\n"
	try:
		result = conn.run(script, timeout=10)
		if not result.ok:
			print(f"[ops] WARNING: audit write failed rc={result.rc}: {result.err.strip()}", flush=True)
	except Exception as exc:
		print(f"[ops] WARNING: audit write failed: {exc}", flush=True)


def tail(conn: HostConnection, lines: int = 200) -> list[dict]:
	path = f"{settings.repo_path}/{AUDIT_FILE}"
	result = conn.run(f"tail -n {int(lines)} {shlex.quote(path)} 2>/dev/null || true", timeout=15)
	records = []
	for raw in result.out.splitlines():
		raw = raw.strip()
		if not raw:
			continue
		try:
			records.append(json.loads(raw))
		except ValueError:
			records.append({"ts": "", "action": "unparseable", "raw": raw[:200]})
	records.reverse()
	return records
