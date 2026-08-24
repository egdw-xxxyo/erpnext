# Ops dashboard

Small FastAPI app that watches the ERPNext stack on the same host and drives
`./deploy` / `./updateRepo` / backup / restore with a live console.

Full documentation (Ukrainian): [`../docs/ops-dashboard.md`](../docs/ops-dashboard.md).

## Quick start on a server

```bash
cp ../.ops.env.example ../.ops.env   # set OPS_SESSION_SECRET, OPS_ENV_LABEL, OPS_ALLOWED_USERS
../deploy ops up                     # http://<host>:8081
```

## Layout

| Path | Role |
|---|---|
| `app/config.py` | environment settings |
| `app/ssh.py` | paramiko connection; the only way this app touches the host |
| `app/sessions.py` | session store; each session owns one SSH connection |
| `app/auth.py` | login/logout, allowlist, timing floor |
| `app/lockout.py` | login throttling, persisted to `/data` |
| `app/stats.py` | one batched host script + TTL cache |
| `app/jobs.py` | detached `setsid` job runner, offset-resumable logs |
| `app/commands.py` | the complete set of runnable commands |
| `app/audit.py` | append-only audit written as the operator |
| `app/routes/` | dashboard, panels, actions, jobs (SSE) |

## Non-negotiables

- `uvicorn --workers 1` — SSH connections and sessions are in-process state.
- The HTTP layer never accepts a shell string; everything goes through `commands.py`.
- The ops container is its own compose project (`-p ops`), never part of `-p docker`.
