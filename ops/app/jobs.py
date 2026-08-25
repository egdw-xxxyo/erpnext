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
import shlex
import time
import uuid

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
  echo "=== @LABEL@ ===" >> "$J.log"
  set +e
  @COMMAND@ >> "$J.log" 2>&1
  rc=$?
  echo "DEPLOY_EXIT=$rc" >> "$J.log"
  echo $rc > "$J.exit"
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
  \( -name '*.log' -o -name '*.meta' -o -name '*.pid' -o -name '*.state' -o -name '*.exit' \) -delete
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
		LABEL=label.replace("'", ""),
	)
	result = conn.run(script, timeout=20)
	state = result.text.splitlines()[-1] if result.text else "unknown"
	if state == "rejected":
		raise JobBusy("another ops job is already running")
	if result.rc != 0 and state not in {"running", "rejected"}:
		raise RuntimeError(f"could not start job: rc={result.rc} {result.err.strip()}")
	return job_id


def _assert_no_single_quote(command: str) -> str:
	if "'" in command:
		raise ValueError("command contains a single quote; not representable in the job wrapper")
	return command


def status(conn: HostConnection, job_id: str) -> dict:
	if not job_id.isalnum():
		raise ValueError("bad job id")
	result = conn.run(_render(STATUS_SCRIPT, job_id), timeout=15)
	try:
		return json.loads(result.text or "{}")
	except ValueError:
		return {"id": job_id, "state": "unknown", "error": result.err.strip()[:200]}


def sweep(conn: HostConnection) -> None:
	try:
		conn.run(_render(SWEEP_SCRIPT, "-"), timeout=30)
	except Exception as exc:
		print(f"[ops] job sweep failed: {exc}", flush=True)


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
