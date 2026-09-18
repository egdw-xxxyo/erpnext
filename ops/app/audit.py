"""Append-only audit trail, written on the host as the authenticated operator.

Writing it through the operator's own SSH session means file ownership
corroborates the recorded username — the dashboard cannot forge a line as
somebody else, because it has no credentials of its own. That host file stays
the source of truth for exactly that reason.

Every line is also mirrored into the `audit` table of the ops database
(store.py). The mirror is what makes the trail searchable by user or action and
what keeps history once `.ops-jobs/` is swept; it is never consulted to decide
whether something happened, only to find it faster.
"""

from __future__ import annotations

import json
import shlex
import time

from . import store
from .config import settings
from .ssh import HostConnection

AUDIT_FILE = ".ops-jobs/audit.log"


def _record(**fields) -> dict:
	fields.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
	return fields


def _line(record: dict) -> str:
	return json.dumps(record, ensure_ascii=False, sort_keys=True)


def _index(record: dict) -> None:
	try:
		store.audit_add(record)
	except Exception as exc:
		print(f"[ops] WARNING: audit index write failed: {exc}", flush=True)


def write(conn: HostConnection, **fields) -> None:
	"""Append one JSONL record. Never raises — a failed audit write must not
	break the action the operator asked for, but it is loud in the app log."""
	record = _record(**fields)
	_index(record)
	jobs_dir = shlex.quote(settings.jobs_dir)
	path = shlex.quote(f"{settings.repo_path}/{AUDIT_FILE}")
	lock = shlex.quote(f"{settings.jobs_dir}/.audit.lock")
	payload = shlex.quote(_line(record))
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
			record = json.loads(raw)
		except ValueError:
			records.append({"ts": "", "action": "unparseable", "raw": raw[:200]})
			continue
		records.append(record)
		# Lines written before this mirror existed, or by ./deploy itself
		# rather than through write(), are picked up here.
		_index(record)
	records.reverse()
	return records


def search(limit: int = 200, username: str = "", action: str = "", since: str = "") -> list[dict]:
	"""Query the mirror. Reaches further back than `tail`, and needs no SSH."""
	try:
		return store.audit_search(limit=limit, username=username, action=action, since=since)
	except Exception as exc:
		print(f"[ops] WARNING: audit search failed: {exc}", flush=True)
		return []
