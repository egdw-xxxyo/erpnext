"""Detached job execution on the host.

A deploy takes ten minutes and must not be tied to the HTTP request, the SSH
channel, or even this container's lifetime — rebuilding the dashboard from the
dashboard is a supported action. So the command is launched with setsid into
its own process group, writes to a log file on the host, and the browser reads
that file back by byte offset. Nothing in the chain holds state that a restart
would lose.
"""

from __future__ import annotations

import json
import re
import shlex
import time
import uuid

from . import store
from .config import settings
from .ssh import HostConnection

# Only one job at a time: two concurrent `docker build`s on a 4-core box with
# 15GB free is how you get a half-built image and a full disk.
LAUNCH_SCRIPT = r"""
set -e
cd @REPO@
mkdir -p .ops-jobs
J=".ops-jobs/@ID@"
printf '%s' @META@ > "$J.meta"
: > "$J.log"

# All of setsid + nohup + </dev/null + redirected stdout are required. Drop any
# one and either exec_command blocks until the child exits, or sshd SIGHUPs the
# job when this session (or the whole ops container) goes away.
setsid nohup bash -c '
  J=".ops-jobs/@ID@"
  # The lock is held by THIS process, not the launcher, so it lives exactly as
  # long as the job. A flock -c wrapper in the launcher would release the
  # moment the launcher returned.
  exec 9>>.ops-jobs/.lock
  if ! flock -n 9; then
    echo rejected > "$J.state"
    echo "ERROR: another ops job is already running." >> "$J.log"
    echo 9 > "$J.exit"
    exit 9
  fi
  echo $$ > "$J.pid"
  echo running > "$J.state"
  # ./deploy and ./updateRepo append one line per milestone here (tools/ops-progress.sh).
  # A side file, not the log: the dashboard polls it every few seconds and the
  # log is tens of megabytes of docker build output.
  : > "$J.progress"
  export OPS_PHASE_LOG="$PWD/$J.progress"
  # Markers also go inline into the log, by path rather than through stdout:
  # under --silent each step redirects its own stdout away, which used to lose
  # every marker but the last few. The console needs them in the log to jump
  # from a step row to the output that step produced.
  # NB: no apostrophe anywhere in this body — it is a single-quoted bash -c.
  export OPS_JOB_LOG="$PWD/$J.log"
  echo "=== @LABEL@ ===" >> "$J.log"
  # Start and end of the whole run, same format as tools/ops-progress.sh.
  ops_mark() {
    printf "%s\n" "[OPS] $(date -u +%Y-%m-%dT%H:%M:%SZ) job $*" | tee -a "$J.progress" >> "$J.log"
  }
  ops_mark start "@LABEL@"
  set +e
  @COMMAND@ >> "$J.log" 2>&1
  rc=$?
  if [ "$rc" = 0 ]; then ops_mark ok "exit 0"; else ops_mark fail "exit $rc"; fi
  echo "DEPLOY_EXIT=$rc" >> "$J.log"
  echo $rc > "$J.exit"
  # Timings of the last five successful runs per action feed the time-left
  # estimates. Kept outside the 14-day sweep (it only looks at depth 1).
  if [ "$rc" = 0 ]; then
    H=".ops-jobs/history/@ACTION@"
    mkdir -p "$H"
    cp "$J.progress" "$H/$(date -u +%Y%m%dT%H%M%S)-@ID@.progress"
    ls -1 "$H"/*.progress 2>/dev/null | sort -r | tail -n +6 | xargs -r rm -f
  fi
' >> "$J.log" 2>&1 </dev/null &
disown

# Give the child a moment to take (or fail to take) the lock so the caller can
# report "busy" synchronously instead of showing an empty console.
for _ in $(seq 1 30); do
  [ -s "$J.state" ] && break
  sleep 0.1
done
cat "$J.state" 2>/dev/null || echo unknown
"""

STATUS_SCRIPT = r"""
cd @REPO@ 2>/dev/null || exit 90
J=".ops-jobs/@ID@"
[ -f "$J.meta" ] || { echo '{"error":"no such job"}'; exit 0; }
EXIT=$(cat "$J.exit" 2>/dev/null)
PID=$(cat "$J.pid" 2>/dev/null)
STATE=$(cat "$J.state" 2>/dev/null)
SIZE=$(stat -c %s "$J.log" 2>/dev/null || echo 0)
if [ -n "$EXIT" ]; then
  [ "$EXIT" = "0" ] && S=success || S=failed
elif [ "$STATE" = "rejected" ]; then
  S=rejected
elif [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  S=running
else
  S=crashed
fi
printf '{"id":"@ID@","state":"%s","exit":"%s","pid":"%s","log_size":%s}\n' "$S" "$EXIT" "$PID" "${SIZE:-0}"
"""

SWEEP_SCRIPT = r"""
cd @REPO@ 2>/dev/null || exit 0
[ -d .ops-jobs ] || exit 0
# Artifacts older than 14 days are gone; a job whose pid is dead with no .exit
# crashed (OOM, reboot, kill -9) and is recorded as such rather than sitting at
# "running" forever.
find .ops-jobs -maxdepth 1 -type f -mtime +14 \
  \( -name '*.log' -o -name '*.meta' -o -name '*.pid' -o -name '*.state' -o -name '*.exit' \
     -o -name '*.progress' \) -delete
for pidfile in .ops-jobs/*.pid; do
  [ -e "$pidfile" ] || continue
  base="${pidfile%.pid}"
  [ -f "$base.exit" ] && continue
  pid=$(cat "$pidfile" 2>/dev/null)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    echo "crashed" > "$base.state"
    echo 137 > "$base.exit"
    echo "ERROR: job process disappeared without an exit code." >> "$base.log"
  fi
done
"""


def _assert_quotable_body(script: str) -> None:
	"""The job body runs as `bash -c '<body>'`, so a single quote anywhere in
	it — including in a comment — ends the string and the launch dies with
	"unexpected EOF while looking for matching `\''". Checked at import so it
	is a failed build, not a failed deploy at 3am."""
	_, _, rest = script.partition("bash -c '")
	body, _, _ = rest.rpartition("' >>")
	if "'" in body:
		raise AssertionError("LAUNCH_SCRIPT body contains a single quote; bash -c would break on it")


_assert_quotable_body(LAUNCH_SCRIPT)


class JobBusy(Exception):
	"""Another job holds the lock."""


def _render(template: str, job_id: str, **extra: str) -> str:
	out = template.replace("@REPO@", shlex.quote(settings.repo_path)).replace("@ID@", job_id)
	for key, value in extra.items():
		out = out.replace(f"@{key}@", value)
	return out


def launch(conn: HostConnection, action: str, command: str, label: str, username: str, args: dict) -> str:
	"""Start a detached job and return its id. Raises JobBusy when one is running."""
	job_id = uuid.uuid4().hex[:16]
	meta = json.dumps(
		{
			"action": action,
			"label": label,
			"command": command,
			"user": username,
			"args": args,
			"started": int(time.time()),
		},
		ensure_ascii=False,
	)
	script = _render(
		LAUNCH_SCRIPT,
		job_id,
		META=shlex.quote(meta),
		# Substituted into a single-quoted bash -c body, so a literal ' would
		# break out. Commands come from the fixed table in commands.py and are
		# already shlex-quoted, but reject the impossible case rather than
		# assume it.
		COMMAND=_assert_no_single_quote(command),
		LABEL=label.replace("'", "").replace('"', ""),
		ACTION=re.sub(r"[^A-Za-z0-9_-]", "", action) or "other",
	)
	result = conn.run(script, timeout=20)
	state = result.text.splitlines()[-1] if result.text else "unknown"
	if state == "rejected":
		raise JobBusy("another ops job is already running")
	if result.rc != 0 and state not in {"running", "rejected"}:
		raise RuntimeError(f"could not start job: rc={result.rc} {result.err.strip()}")
	_index_start(job_id, action, label, username, args)
	return job_id


#: A run recorded as finished in the index is never touched again, so the
#: [OPS] markers of a run outlive the 14-day sweep of .ops-jobs/.
TERMINAL_STATES = {"success", "failed", "crashed", "rejected"}


def _index_start(job_id: str, action: str, label: str, username: str, args: dict) -> None:
	try:
		store.job_started(job_id, action, label, username, args, time.time())
	except Exception as exc:
		print(f"[ops] WARNING: could not index job start: {exc}", flush=True)


def _index_finish(conn: HostConnection, job_id: str, state: dict) -> None:
	"""Called from the polled status endpoint: the only moment ops reliably
	learns that a host-side job ended."""
	if state.get("state") not in TERMINAL_STATES:
		return
	try:
		if not store.job_pending(job_id):
			return
		try:
			steps = progress_lines(conn, job_id)
		except Exception:
			steps = []
		exit_raw = str(state.get("exit") or "").strip()
		store.job_finished(
			job_id,
			str(state["state"]),
			int(exit_raw) if exit_raw.isdigit() else None,
			steps,
		)
		_archive_log(conn, job_id)
	except Exception as exc:
		print(f"[ops] WARNING: could not index job finish: {exc}", flush=True)


def _archive_log(conn: HostConnection, job_id: str) -> None:
	"""Copy the finished run's log into the database.

	The host file is left in place: consoles opened on this job are still
	streaming it, and it is the copy that survives ops itself dying. The
	14-day sweep is what eventually removes it — from then on the console
	reads this archive instead."""
	try:
		result = conn.run(_render(READ_LOG_SCRIPT, job_id), timeout=60)
	except Exception as exc:
		print(f"[ops] WARNING: could not read log of {job_id} to archive: {exc}", flush=True)
		return
	if result.rc != 0:
		return
	store.job_log_put(job_id, result.out)


def _assert_no_single_quote(command: str) -> str:
	if "'" in command:
		raise ValueError("command contains a single quote; not representable in the job wrapper")
	return command


def status(conn: HostConnection, job_id: str) -> dict:
	if not job_id.isalnum():
		raise ValueError("bad job id")
	result = conn.run(_render(STATUS_SCRIPT, job_id), timeout=15)
	try:
		state = json.loads(result.text or "{}")
	except ValueError:
		return {"id": job_id, "state": "unknown", "error": result.err.strip()[:200]}
	if state.get("error"):
		# Swept off the host: answer from the index instead of "no such job".
		archived = _status_from_index(job_id)
		if archived:
			return archived
	_index_finish(conn, job_id, state)
	return state


def _status_from_index(job_id: str) -> dict | None:
	try:
		row = store.job_run_get(job_id)
	except Exception:
		return None
	if not row or row.get("finished") is None:
		return None
	return {
		"id": job_id,
		"state": row["state"],
		"exit": "" if row["exit_code"] is None else str(row["exit_code"]),
		"pid": "",
		"log_size": 0,
		"archived": True,
	}


READ_LOG_SCRIPT = r"""
cd @REPO@ 2>/dev/null || exit 1
[ -f ".ops-jobs/@ID@.log" ] || exit 1
cat ".ops-jobs/@ID@.log"
"""

PROGRESS_SCRIPT = r"""
cd @REPO@ 2>/dev/null || exit 0
cat ".ops-jobs/@ID@.progress" 2>/dev/null && exit 0
for f in .ops-jobs/history/*/*-@ID@.progress; do
  [ -f "$f" ] && cat "$f" && exit 0
done
"""


def progress_lines(conn: HostConnection, job_id: str) -> list[str]:
	"""[OPS] markers of one run: its own side file, the history copy once
	swept, or the set captured into the index when the run finished."""
	if not job_id.isalnum():
		raise ValueError("bad job id")
	result = conn.run(_render(PROGRESS_SCRIPT, job_id), timeout=15)
	lines = [line for line in (result.text or "").splitlines() if line.strip()]
	if lines:
		return lines
	return indexed_steps(job_id)


def indexed_steps(job_id: str) -> list[str]:
	try:
		row = store.job_run_get(job_id)
		return json.loads(row["steps"]) if row else []
	except Exception:
		return []


def archived_log(job_id: str) -> str | None:
	"""The finished run's log as copied into the database, if it is there."""
	if not job_id.isalnum():
		raise ValueError("bad job id")
	try:
		return store.job_log_get(job_id)
	except Exception as exc:
		print(f"[ops] WARNING: could not read archived log of {job_id}: {exc}", flush=True)
		return None


def ensure_archived(conn: HostConnection, job_id: str) -> str | None:
	"""The log of a finished run, from the database — archiving it first if it
	is not there yet (runs that ended before this existed, or whose archive
	pass failed). None means neither copy is reachable and the caller should
	fall back to the host file."""
	body = archived_log(job_id)
	if body is not None:
		return body
	try:
		_archive_log(conn, job_id)
	except Exception as exc:
		print(f"[ops] WARNING: could not archive log of {job_id} on demand: {exc}", flush=True)
		return None
	return archived_log(job_id)


def sweep(conn: HostConnection) -> None:
	try:
		conn.run(_render(SWEEP_SCRIPT, "-"), timeout=30)
	except Exception as exc:
		print(f"[ops] job sweep failed: {exc}", flush=True)
	try:
		store.prune()
	except Exception as exc:
		print(f"[ops] index prune failed: {exc}", flush=True)


def tail_command(job_id: str, offset: int) -> str:
	"""Shell line that streams the log from `offset`, exiting when the job ends."""
	if not job_id.isalnum():
		raise ValueError("bad job id")
	log = shlex.quote(f"{settings.jobs_dir}/{job_id}.log")
	exit_file = shlex.quote(f"{settings.jobs_dir}/{job_id}.exit")
	pid_file = shlex.quote(f"{settings.jobs_dir}/{job_id}.pid")
	start = max(1, int(offset) + 1)
	# --pid makes tail exit when the job process dies instead of hanging until
	# the browser gives up. If the job is already finished, do not follow at all.
	return (
		f"if [ -f {exit_file} ]; then tail -c +{start} {log}; "
		f"else tail -c +{start} -f --pid=$(cat {pid_file} 2>/dev/null || echo 1) {log}; fi"
	)
