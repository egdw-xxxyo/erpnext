# Ops dashboard

Small FastAPI app that watches the ERPNext stack on the same host and drives
`./deploy` / `./updateRepo` / backup / restore with a live console.

Full documentation (Ukrainian): [`../docs/ops-dashboard.md`](../docs/ops-dashboard.md).

## Quick start on a server

```bash
cp ../.ops.env.example ../.ops.env   # set OPS_SESSION_SECRET, OPS_ENV_LABEL, OPS_ALLOWED_USERS
../deploy ops up                     # http://<host>:8081
```

No sshd on this machine (e.g. a laptop)? Set `OPS_LOCAL_MODE=1` in `.ops.env`
too — see the comment above it in `.ops.env.example`. Login then only checks
`OPS_ALLOWED_USERS`, no password, and commands run inside the ops container
itself (`docker-compose.ops.local.yml` bind-mounts the repo + docker socket
in for that). Never set it on a shared host.

## Layout

| Path | Role |
|---|---|
| `app/config.py` | environment settings |
| `app/ssh.py` | paramiko connection; the only way this app touches a real host |
| `app/local_conn.py` | `OPS_LOCAL_MODE=1` alternative: runs commands in this container instead of SSH — dev setups with no sshd |
| `app/sessions.py` | session store; each session owns one SSH connection |
| `app/auth.py` | login/logout, allowlist, timing floor |
| `app/lockout.py` | login throttling, persisted in the ops database |
| `app/stats.py` | one batched host script + TTL cache |
| `app/jobs.py` | detached `setsid` job runner, offset-resumable logs |
| `app/commands.py` | the complete set of runnable commands |
| `app/audit.py` | append-only audit written as the operator |
| `app/ftp_config.py` | encrypted-at-rest config for off-host FTP backup targets (multiple, each tagged prod/dev/test) |
| `app/ftp.py` | push/pull/list against that target (netrc-file staged on host, never in argv/logs) |
| `app/schedule.py` | scheduled backup as a marked line in the host's own crontab (no in-app scheduler) |
| `app/store.py` | SQLite (`/data/ops.db`): prefs, lockout, encrypted secrets, job-run and audit index |
| `app/prefs.py` | tiny plaintext KV store (currently: the pre-deploy safety-backup toggle) |
| `app/git_keys.py` | encrypted-at-rest per-ops-user git SSH deploy key |
| `app/git_ssh.py` | stages that key on the host and wraps `update-repo`/`switch-branch` with `GIT_SSH_COMMAND` |
| `app/routes/` | dashboard, panels, actions, jobs (SSE), settings (FTP targets), git_key_settings, schedule, remote_backups |

## Where state lives

Two places, on purpose.

**On the host, in `<repo>/.ops-jobs/`** — written by `./deploy` itself, under the
operator's own account:

| File | Role |
|---|---|
| `<id>.log` | job output, streamed to the browser by byte offset |
| `<id>.meta/.pid/.state/.exit` | the run's card |
| `<id>.progress`, `history/<action>/` | `[OPS]` milestone markers and the last five runs per action (also written inline into the log, so the console can jump to a step) |
| `audit.log` | append-only JSONL, written under `flock` |

These are the source of truth. They survive this container being rebuilt by the
very deploy they belong to, and the audit file's ownership corroborates the
username in each line — ops has no host credentials of its own to forge one
with. `jobs.py`'s sweep deletes artifacts older than 14 days.

**In the container, `/data/ops.db`** (volume `ops-data`, SQLite + WAL) — state
that belongs to the dashboard:

| Table | Role |
|---|---|
| `kv` | preferences (`prefs.py`) |
| `lockout` | login failure counters, so a restart does not clear a lockout |
| `secret` | Fernet blobs: FTP server/targets, per-user git deploy keys. Ciphertext only — same bytes the `.enc` files held |
| `job_run` | one row per launched job, with its `[OPS]` steps captured at finish — timings outlive the 14-day sweep |
| `job_log` | the finished run's log, zlib-compressed. What the console reads for any job that is not still running |
| `audit` | mirror of `audit.log`, for search by user/action and history past the sweep |

`prefs.json`, `lockout.json` and the `*.enc` files from before the database are
imported on first boot and renamed `*.imported` (`store.migrate_from_files`).

A **running** job streams from the host file by byte offset — that is the only
copy being written, and the offset is what lets the console survive the deploy
restarting this container. The moment the job ends its log is copied into
`job_log`, and from then on the console reads the database: one local read
instead of an SSH tail over a file the sweep, a disk cleanup or a rebuilt host
may no longer have. The host file itself is left alone until the sweep — open
consoles are still reading it, and it is the copy that outlives ops crashing.
Logs over 4 MB keep their first 128 KB and last 4 MB. `store.prune()` (hourly,
from the sweep) keeps the last 200 runs and 20 000 audit lines.

## Non-negotiables

- `uvicorn --workers 1` — SSH connections and sessions are in-process state.
- Panels set their own poll rate: `partials/*.html` render `data-poll="<seconds>"` and `console.js` rewrites the container's `hx-trigger`. Actions and Jobs ask for 1s while a job runs, 15s when idle — never poll everything at 1s all day.
- The HTTP layer never accepts a shell string; everything goes through `commands.py`.
- The ops container is its own compose project (`-p ops`), never part of `-p docker`.
- Job logs and the audit trail stay files on the host. `ops.db` only indexes them — never treat a missing row as "it did not happen".
