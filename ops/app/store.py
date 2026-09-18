"""SQLite store for everything the dashboard keeps for itself.

Scope, deliberately: only state that belongs to *ops*, never state that belongs
to the host. Job logs, `[OPS]` progress markers and the append-only audit trail
are written on the host by `./deploy` itself, under the operator's own account,
and have to survive this container being rebuilt mid-deploy — those stay files
in `.ops-jobs/` and are still the source of truth. What lives here is the
container's own `/data`: preferences, login throttling, encrypted secrets, plus
a queryable *index* of job runs and audit lines that the file layer can only
answer by globbing and tailing.

One file (`$OPS_DATA_DIR/ops.db`), WAL, one connection shared by the process —
uvicorn runs a single worker, and every write is short. Blocking sqlite calls
are fine on the event loop at this size (sub-millisecond, local disk); the SSH
round-trips they replace were the slow part.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .config import settings

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
	key        TEXT PRIMARY KEY,
	value      TEXT NOT NULL,
	updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lockout (
	key          TEXT PRIMARY KEY,
	failures     TEXT NOT NULL DEFAULT '[]',
	locked_until REAL NOT NULL DEFAULT 0
);

-- Encrypted-at-rest blobs (Fernet, key = OPS_SECRET_KEY). The database never
-- sees plaintext: it stores exactly the bytes the .enc files used to hold.
CREATE TABLE IF NOT EXISTS secret (
	name       TEXT PRIMARY KEY,
	blob       BLOB NOT NULL,
	updated_at REAL NOT NULL
);

-- One row per launched job. `steps` is the [OPS] marker list captured when the
-- run finished, so timings survive the 14-day sweep of .ops-jobs/.
CREATE TABLE IF NOT EXISTS job_run (
	id        TEXT PRIMARY KEY,
	action    TEXT NOT NULL,
	label     TEXT NOT NULL DEFAULT '',
	username  TEXT NOT NULL DEFAULT '',
	args      TEXT NOT NULL DEFAULT '{}',
	started   REAL NOT NULL,
	finished  REAL,
	exit_code INTEGER,
	state     TEXT NOT NULL DEFAULT 'running',
	steps     TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS job_run_action_started ON job_run (action, started DESC);
CREATE INDEX IF NOT EXISTS job_run_started ON job_run (started DESC);

-- The job log, zlib-compressed, copied off the host once the run ends. The
-- host file stays until the 14-day sweep; this is what the console falls back
-- to afterwards.
CREATE TABLE IF NOT EXISTS job_log (
	job_id    TEXT PRIMARY KEY REFERENCES job_run (id) ON DELETE CASCADE,
	body      BLOB NOT NULL,
	raw_size  INTEGER NOT NULL,
	truncated INTEGER NOT NULL DEFAULT 0,
	created   REAL NOT NULL
);

-- Mirror of the host-side audit.log, for search and retention beyond the
-- 14-day sweep. The host file stays authoritative: it is the copy whose
-- ownership corroborates the recorded username.
CREATE TABLE IF NOT EXISTS audit (
	id      INTEGER PRIMARY KEY AUTOINCREMENT,
	ts      TEXT NOT NULL,
	username TEXT NOT NULL DEFAULT '',
	action  TEXT NOT NULL DEFAULT '',
	payload TEXT NOT NULL,
	digest  TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit (ts DESC);
CREATE INDEX IF NOT EXISTS audit_user_ts ON audit (username, ts DESC);
"""


def path() -> str:
	return os.path.join(settings.data_dir, "ops.db")


def connection() -> sqlite3.Connection:
	global _conn
	with _lock:
		if _conn is None:
			os.makedirs(settings.data_dir, exist_ok=True)
			conn = sqlite3.connect(path(), check_same_thread=False)
			conn.row_factory = sqlite3.Row
			conn.execute("PRAGMA journal_mode=WAL")
			conn.execute("PRAGMA synchronous=NORMAL")
			conn.execute("PRAGMA busy_timeout=5000")
			conn.executescript(SCHEMA)
			conn.commit()
			try:
				os.chmod(path(), 0o600)
			except OSError:
				pass
			_conn = conn
		return _conn


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
	"""One short transaction. The process-wide lock keeps concurrent request
	threads from interleaving read-modify-write pairs (lockout counters)."""
	conn = connection()
	with _lock:
		try:
			yield conn
			conn.commit()
		except Exception:
			conn.rollback()
			raise


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
	with _lock:
		return connection().execute(sql, params).fetchall()


# ---- key/value (preferences) ------------------------------------------------


def kv_get(key: str, default: Any = None) -> Any:
	rows = query("SELECT value FROM kv WHERE key = ?", (key,))
	if not rows:
		return default
	try:
		return json.loads(rows[0]["value"])
	except ValueError:
		return default


def kv_set(key: str, value: Any) -> None:
	with write() as conn:
		conn.execute(
			"INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?) "
			"ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
			(key, json.dumps(value), time.time()),
		)


# ---- secrets ----------------------------------------------------------------


def secret_get(name: str) -> bytes | None:
	rows = query("SELECT blob FROM secret WHERE name = ?", (name,))
	return bytes(rows[0]["blob"]) if rows else None


def secret_set(name: str, blob: bytes) -> None:
	with write() as conn:
		conn.execute(
			"INSERT INTO secret (name, blob, updated_at) VALUES (?, ?, ?) "
			"ON CONFLICT(name) DO UPDATE SET blob = excluded.blob, updated_at = excluded.updated_at",
			(name, blob, time.time()),
		)


def secret_delete(name: str) -> None:
	with write() as conn:
		conn.execute("DELETE FROM secret WHERE name = ?", (name,))


# ---- lockout ----------------------------------------------------------------


def lockout_load() -> tuple[dict[str, list[float]], dict[str, float]]:
	failures: dict[str, list[float]] = {}
	locked_until: dict[str, float] = {}
	for row in query("SELECT key, failures, locked_until FROM lockout"):
		try:
			failures[row["key"]] = list(json.loads(row["failures"]))
		except ValueError:
			failures[row["key"]] = []
		locked_until[row["key"]] = row["locked_until"] or 0.0
	return failures, locked_until


def lockout_save(key: str, failures: list[float], locked_until: float) -> None:
	with write() as conn:
		if not failures and not locked_until:
			conn.execute("DELETE FROM lockout WHERE key = ?", (key,))
			return
		conn.execute(
			"INSERT INTO lockout (key, failures, locked_until) VALUES (?, ?, ?) "
			"ON CONFLICT(key) DO UPDATE SET failures = excluded.failures, "
			"locked_until = excluded.locked_until",
			(key, json.dumps(failures), locked_until),
		)


def lockout_forget(key: str) -> None:
	with write() as conn:
		conn.execute("DELETE FROM lockout WHERE key = ?", (key,))


# ---- job runs ---------------------------------------------------------------


def job_started(job_id: str, action: str, label: str, username: str, args: dict, started: float) -> None:
	with write() as conn:
		conn.execute(
			"INSERT OR REPLACE INTO job_run (id, action, label, username, args, started, state) "
			"VALUES (?, ?, ?, ?, ?, ?, 'running')",
			(job_id, action, label, username, json.dumps(args, ensure_ascii=False), started),
		)


def job_finished(job_id: str, state: str, exit_code: int | None, steps: list[str]) -> None:
	"""Idempotent: the status endpoint is polled, so this runs many times for
	one job and only the first call with a terminal state records anything."""
	with write() as conn:
		conn.execute(
			"UPDATE job_run SET state = ?, exit_code = ?, finished = ?, steps = ? "
			"WHERE id = ? AND finished IS NULL",
			(state, exit_code, time.time(), json.dumps(steps, ensure_ascii=False), job_id),
		)


def job_runs(action: str | None = None, limit: int = 50) -> list[dict]:
	sql = "SELECT * FROM job_run"
	params: tuple = ()
	if action:
		sql += " WHERE action = ?"
		params = (action,)
	sql += " ORDER BY started DESC LIMIT ?"
	params = (*params, int(limit))
	return [dict(row) for row in query(sql, params)]


def job_run_get(job_id: str) -> dict | None:
	rows = query("SELECT * FROM job_run WHERE id = ?", (job_id,))
	return dict(rows[0]) if rows else None


def job_pending(job_id: str) -> bool:
	"""True while a known run has no terminal state recorded yet."""
	return bool(query("SELECT 1 FROM job_run WHERE id = ? AND finished IS NULL", (job_id,)))


# ---- archived job logs -------------------------------------------------------

#: Kept from the head and the tail of an oversized log. A docker build is
#: hundreds of thousands of lines of layer chatter in the middle; what anyone
#: ever reads back is how it started and how it died.
LOG_HEAD_BYTES = 128 * 1024
LOG_TAIL_BYTES = 4 * 1024 * 1024


def clip_log(text: str) -> tuple[str, int, bool]:
	"""(stored text, original size, truncated?)"""
	raw = text.encode("utf-8", "replace")
	if len(raw) <= LOG_HEAD_BYTES + LOG_TAIL_BYTES:
		return text, len(raw), False
	dropped = len(raw) - LOG_HEAD_BYTES - LOG_TAIL_BYTES
	head = raw[:LOG_HEAD_BYTES].decode("utf-8", "replace")
	tail = raw[-LOG_TAIL_BYTES:].decode("utf-8", "replace")
	marker = f"\n\n[ops] ... {dropped} bytes omitted when this log was archived ...\n\n"
	return head + marker + tail, len(raw), True


def job_log_put(job_id: str, text: str) -> None:
	body, raw_size, truncated = clip_log(text)
	with write() as conn:
		conn.execute(
			"INSERT OR REPLACE INTO job_log (job_id, body, raw_size, truncated, created) "
			"VALUES (?, ?, ?, ?, ?)",
			(job_id, zlib.compress(body.encode("utf-8"), 6), raw_size, int(truncated), time.time()),
		)


def job_log_get(job_id: str) -> str | None:
	rows = query("SELECT body FROM job_log WHERE job_id = ?", (job_id,))
	if not rows:
		return None
	try:
		return zlib.decompress(bytes(rows[0]["body"])).decode("utf-8", "replace")
	except zlib.error as exc:
		print(f"[ops] WARNING: archived log for {job_id} is unreadable: {exc}", flush=True)
		return None


def job_log_stored(job_id: str) -> bool:
	return bool(query("SELECT 1 FROM job_log WHERE job_id = ?", (job_id,)))


#: How much history the database keeps. The host sweeps its own artifacts after
#: 14 days; these bounds are what stops ops.db growing without limit in their
#: place. ~200 runs of compressed deploy output is single-digit megabytes.
KEEP_RUNS = 200
KEEP_AUDIT = 20000


def prune(keep_runs: int = KEEP_RUNS, keep_audit: int = KEEP_AUDIT) -> None:
	"""Drop the oldest runs and audit lines. Called from the hourly sweep."""
	with write() as conn:
		conn.execute(
			"DELETE FROM job_log WHERE job_id IN ("
			"  SELECT id FROM job_run ORDER BY started DESC LIMIT -1 OFFSET ?"
			")",
			(int(keep_runs),),
		)
		conn.execute(
			"DELETE FROM job_run WHERE id IN (SELECT id FROM job_run ORDER BY started DESC LIMIT -1 OFFSET ?)",
			(int(keep_runs),),
		)
		conn.execute(
			"DELETE FROM audit WHERE id IN (SELECT id FROM audit ORDER BY id DESC LIMIT -1 OFFSET ?)",
			(int(keep_audit),),
		)


# ---- audit index ------------------------------------------------------------


def audit_add(record: dict) -> None:
	"""Insert one audit line.

	`digest` is the serialized record itself, which makes re-importing the host
	file idempotent — at the cost of collapsing two byte-identical lines from
	the same second (timestamps are second-resolution). The host file keeps
	both; this is an index, not the record."""
	payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
	with write() as conn:
		conn.execute(
			"INSERT OR IGNORE INTO audit (ts, username, action, payload, digest) VALUES (?, ?, ?, ?, ?)",
			(
				str(record.get("ts") or ""),
				str(record.get("user") or ""),
				str(record.get("action") or ""),
				payload,
				payload,
			),
		)


def audit_search(limit: int = 200, username: str = "", action: str = "", since: str = "") -> list[dict]:
	sql = "SELECT payload FROM audit WHERE 1 = 1"
	params: list = []
	if username:
		sql += " AND username = ?"
		params.append(username)
	if action:
		sql += " AND action = ?"
		params.append(action)
	if since:
		sql += " AND ts >= ?"
		params.append(since)
	sql += " ORDER BY ts DESC, id DESC LIMIT ?"
	params.append(int(limit))
	out = []
	for row in query(sql, tuple(params)):
		try:
			out.append(json.loads(row["payload"]))
		except ValueError:
			continue
	return out


def audit_count() -> int:
	return query("SELECT COUNT(*) AS n FROM audit")[0]["n"]


# ---- one-shot import of the pre-SQLite files --------------------------------

#: `/data` filename -> secret name. Kept verbatim (still Fernet blobs).
_SECRET_FILES = {
	"ftp_server.enc": "ftp_server",
	"ftp_targets.enc": "ftp_targets",
	"ftp_config.enc": "ftp_config_legacy",
}


def migrate_from_files() -> None:
	"""Import prefs.json, lockout.json and the .enc blobs written before this
	module existed, then rename them aside. Safe to run on every boot: an
	already-imported file is gone, and an unreadable one is skipped loudly."""
	data_dir = settings.data_dir
	if not os.path.isdir(data_dir):
		return

	_import_json_file(os.path.join(data_dir, "prefs.json"), _import_prefs)
	_import_json_file(os.path.join(data_dir, "lockout.json"), _import_lockout)

	for filename, name in _SECRET_FILES.items():
		_import_secret_file(os.path.join(data_dir, filename), name)

	for filename in sorted(os.listdir(data_dir)):
		if filename.startswith("git_key_") and filename.endswith(".enc"):
			username = filename[len("git_key_") : -len(".enc")]
			_import_secret_file(os.path.join(data_dir, filename), f"git_key_{username}")


def _retire(path_: str) -> None:
	try:
		os.replace(path_, path_ + ".imported")
	except OSError as exc:
		print(f"[ops] WARNING: could not retire {path_} after import: {exc}", flush=True)


def _import_json_file(path_: str, handler) -> None:
	try:
		with open(path_) as fh:
			data = json.load(fh)
	except FileNotFoundError:
		return
	except (OSError, ValueError) as exc:
		print(f"[ops] WARNING: could not import {path_}: {exc}", flush=True)
		return
	handler(data)
	_retire(path_)
	print(f"[ops] imported {os.path.basename(path_)} into {os.path.basename(path())}", flush=True)


def _import_prefs(data: dict) -> None:
	for key, value in (data or {}).items():
		if kv_get(key, _MISSING) is _MISSING:
			kv_set(key, value)


def _import_lockout(data: dict) -> None:
	failures = (data or {}).get("failures") or {}
	locked_until = (data or {}).get("locked_until") or {}
	for key in set(failures) | set(locked_until):
		lockout_save(key, list(failures.get(key) or []), float(locked_until.get(key) or 0.0))
	if (data or {}).get("global_until"):
		kv_set("lockout_global_until", float(data["global_until"]))


def _import_secret_file(path_: str, name: str) -> None:
	try:
		with open(path_, "rb") as fh:
			blob = fh.read()
	except FileNotFoundError:
		return
	except OSError as exc:
		print(f"[ops] WARNING: could not import {path_}: {exc}", flush=True)
		return
	if secret_get(name) is None:
		secret_set(name, blob)
	_retire(path_)
	print(f"[ops] imported {os.path.basename(path_)} into {os.path.basename(path())}", flush=True)


class _Missing:
	pass


_MISSING = _Missing()
