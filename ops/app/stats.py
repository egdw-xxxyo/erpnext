"""Host stat collection.

One SSH round-trip per refresh, not one per panel. The script below emits a
single JSON document; every field is individually guarded so a missing binary
yields an empty value instead of aborting the whole collection.

Results are cached per host (not per session) so N open browsers still cost one
round-trip per TTL.

The scripts are plain strings with @TOKEN@ placeholders rather than f-strings —
shell and embedded Python are dense with braces, and escaping every one of them
for str.format is how these break silently.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from typing import Any

from .config import settings
from .ssh import HostConnection

FAST_TTL = 10.0
BACKUPS_TTL = 60.0
DISK_DETAIL_TTL = 600.0


# Shared by the stats script and ./deploy: parse `<name> <epoch> <bytes> <files>`
# lines into JSON.
_BACKUP_PARSER = """python3 -c 'import sys,json
out=[]
for line in sys.stdin:
    p=line.split()
    if len(p)==4:
        out.append({"name":p[0],"epoch":int(p[1]),"bytes":int(p[2]),"with_files":p[3]=="yes"})
print(json.dumps(out))'"""


# `docker compose ps --format json` emits either a JSON array or one object per
# line depending on the compose version; handle both. Fields are projected
# host-side because the raw rows carry every compose label — ~12KB per poll
# that we would otherwise pull over SSH ten times a minute and throw away.
def _rows_parser(*fields: str) -> str:
	keys = ",".join(f'"{f}"' for f in fields)
	return f"""python3 -c 'import json,sys
raw=sys.stdin.read().strip()
rows=json.loads(raw) if raw.startswith("[") else [json.loads(l) for l in raw.splitlines() if l.strip()]
keep=({keys},)
print(json.dumps([{{k: r.get(k, "") for k in keep}} for r in rows]))'"""


_PS_PARSER = _rows_parser("Service", "Name", "State", "Status", "Health")
_DF_PARSER = _rows_parser("Type", "TotalCount", "Active", "Size", "Reclaimable")

STATS_SCRIPT = r"""
cd @REPO@ 2>/dev/null || exit 90
DC="docker compose -p @PROJECT@ -f @REPO@/docker-compose.yml"
BACKUP_DIR="/home/frappe/frappe-bench/sites/@SITE@/private/backups"

echo '{'

# ---- git -------------------------------------------------------------------
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
HEAD=$(git rev-parse --short HEAD 2>/dev/null)
TAG=$(git tag --points-at HEAD 2>/dev/null | tail -1)
DESCRIBE=$(git describe --tags --always --dirty 2>/dev/null)
# -uno: untracked files do not block anything. Prod permanently carries
# untracked hrms_app/ and site-config.json.bak, and counting those as
# "dirty" would disable switch-branch forever.
DIRTY=$([ -z "$(git status --porcelain -uno 2>/dev/null)" ] && echo false || echo true)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
BEHIND=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo "")
MERGE=$([ "$(git rev-list --no-walk --count --merges HEAD 2>/dev/null)" = "1" ] && echo true || echo false)
printf '"git": {"branch":"%s","head":"%s","tag":"%s","describe":"%s","dirty":%s,"behind":"%s","merge":%s,"untracked":%s},\n' \
  "$BRANCH" "$HEAD" "$TAG" "$DESCRIBE" "$DIRTY" "$BEHIND" "$MERGE" "${UNTRACKED:-0}"

# ---- containers ------------------------------------------------------------
printf '"containers": '
$DC ps -a --format json 2>/dev/null | @PS_PARSER@ 2>/dev/null || echo '[]'
printf ',\n'

# ---- HTTP health: from the host through nginx, the way a real user hits it --
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 5 @ERP@/api/method/ping 2>/dev/null || echo 000)
SECS=$(curl -s -o /dev/null -w '%{time_total}' -m 5 @ERP@/api/method/ping 2>/dev/null || echo 0)
printf '"http": {"code":"%s","seconds":"%s"},\n' "$CODE" "$SECS"

# ---- db + redis ------------------------------------------------------------
DB=$($DC exec -T db mysqladmin ping --password=admin </dev/null 2>/dev/null | tr -d '\r\n' | grep -o alive || echo "")
RC=$($DC exec -T redis-cache redis-cli ping </dev/null 2>/dev/null | tr -d '\r\n' || echo "")
RQ=$($DC exec -T redis-queue redis-cli ping </dev/null 2>/dev/null | tr -d '\r\n' || echo "")
printf '"db":"%s","redis_cache":"%s","redis_queue":"%s",\n' "$DB" "$RC" "$RQ"

# ---- version ---------------------------------------------------------------
RELEASE=$(ls -1 erpnext/release_notes/ 2>/dev/null | sed 's/\.md$//' | sort -V | tail -1)
IMAGE=$(grep -m1 '^ERPNEXT_VERSION=' deploy 2>/dev/null | cut -d'"' -f2)
SITE_ENV=$(python3 -c "import json;print(json.load(open('site-config.json')).get('environment',''))" 2>/dev/null)
DEPLOY_ENV=$(cat .deploy-env 2>/dev/null | tr -d '[:space:]')
printf '"version": {"release":"%s","image":"%s","site_env":"%s","deploy_env":"%s"},\n' \
  "$RELEASE" "$IMAGE" "$SITE_ENV" "$DEPLOY_ENV"

# ---- disk ------------------------------------------------------------------
read -r DSIZE DUSED DAVAIL DPCT <<<"$(df -B1 --output=size,used,avail,pcent / 2>/dev/null | tail -1)"
JOURNAL=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMGT]' | tail -1)
printf '"disk": {"size":"%s","used":"%s","avail":"%s","pct":"%s","journal":"%s"},\n' \
  "$DSIZE" "$DUSED" "$DAVAIL" "${DPCT%\%}" "$JOURNAL"

printf '"docker_df": '
docker system df --format json 2>/dev/null | @DF_PARSER@ 2>/dev/null || echo '[]'
printf ',\n'

# ---- backups ---------------------------------------------------------------
printf '"backups": '
$DC exec -T backend bash -c '
  d="$1"
  [ -d "$d" ] || exit 0
  for f in "$d"/*-database.sql.gz; do
    [ -e "$f" ] || continue
    b=$(basename "$f"); n=${b%-database.sql.gz}
    sz=$(du -cb "$d/$n"-* 2>/dev/null | tail -1 | cut -f1)
    ts=$(stat -c %Y "$f")
    files=no
    [ -e "$d/$n-files.tar" ] && files=yes
    echo "$n $ts $sz $files"
  done | sort -k2 -nr
' _ "$BACKUP_DIR" </dev/null 2>/dev/null | @BACKUP_PARSER@ 2>/dev/null || echo '[]'
printf ',\n'

# ---- backup free space (same filesystem the sites volume lives on) ---------
BFREE=$($DC exec -T backend df -B1 --output=avail "$BACKUP_DIR" </dev/null 2>/dev/null | tail -1 | tr -d '[:space:]')
printf '"backup_avail":"%s",\n' "$BFREE"

# ---- jobs ------------------------------------------------------------------
printf '"jobs": '
python3 - <<'PYEOF' 2>/dev/null || echo '[]'
import glob, json, os

rows = []
for meta_path in sorted(glob.glob(".ops-jobs/*.meta")):
    jid = os.path.basename(meta_path)[:-5]
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
    except Exception:
        continue

    def read(ext, _jid=jid):
        try:
            with open(".ops-jobs/%s.%s" % (_jid, ext)) as fh:
                return fh.read().strip()
        except OSError:
            return ""

    exit_code, pid, state_file = read("exit"), read("pid"), read("state")
    if exit_code != "":
        state = "success" if exit_code == "0" else "failed"
    elif state_file == "rejected":
        state = "rejected"
    elif pid and os.path.isdir("/proc/%s" % pid):
        state = "running"
    else:
        state = "crashed"
    meta.update(id=jid, state=state, exit=exit_code)
    rows.append(meta)

rows.sort(key=lambda r: r.get("started", 0), reverse=True)
print(json.dumps(rows[:20]))
PYEOF

echo '}'
"""


# Expensive: du over thousands of files plus a builder-cache walk. Behind an
# explicit button, never on the polling path.
DISK_DETAIL_SCRIPT = r"""
cd @REPO@ 2>/dev/null || exit 90
DC="docker compose -p @PROJECT@ -f @REPO@/docker-compose.yml"
PJ=$($DC exec -T backend bash -c '
  cd sites/@SITE@/private/files 2>/dev/null || exit 0
  n=$(ls -1 PJ-*.png 2>/dev/null | wc -l)
  b=$(du -cb PJ-*.png 2>/dev/null | tail -1 | cut -f1)
  echo "${n:-0} ${b:-0}"
' </dev/null 2>/dev/null)
SITES_TOTAL=$($DC exec -T backend du -sb sites </dev/null 2>/dev/null | cut -f1)
printf '{"pj":"%s","sites_bytes":"%s"}\n' "$PJ" "$SITES_TOTAL"
"""


def _render(template: str) -> str:
	return (
		template.replace("@REPO@", shlex.quote(settings.repo_path))
		.replace("@PROJECT@", shlex.quote(settings.compose_project))
		.replace("@SITE@", settings.site)
		.replace("@ERP@", settings.erp_url)
		.replace("@PS_PARSER@", _PS_PARSER)
		.replace("@DF_PARSER@", _DF_PARSER)
		.replace("@BACKUP_PARSER@", _BACKUP_PARSER)
	)


def _normalise_containers(rows: list[dict]) -> list[dict]:
	return [
		{
			"name": r.get("Service") or r.get("Name") or "?",
			"state": r.get("State") or "",
			"status": r.get("Status") or "",
			"health": r.get("Health") or "",
		}
		for r in rows
	]


def _normalise_docker_df(rows: list[dict]) -> list[dict]:
	return [
		{
			"type": r.get("Type") or "",
			"total": r.get("TotalCount") or "",
			"active": r.get("Active") or "",
			"size": r.get("Size") or "",
			"reclaimable": r.get("Reclaimable") or "",
		}
		for r in rows
	]


class StatsCache:
	"""Host-scoped, TTL'd snapshot shared by every logged-in browser."""

	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._data: dict[str, Any] = {}
		self._fetched_at = 0.0
		self._error: str | None = None

	async def get(self, conn: HostConnection, ttl: float = FAST_TTL, force: bool = False) -> dict[str, Any]:
		async with self._lock:
			if not force and self._data and time.time() - self._fetched_at < ttl:
				return self._snapshot()
			try:
				result = await asyncio.to_thread(conn.run, _render(STATS_SCRIPT), 90)
				if result.rc == 90:
					raise RuntimeError(f"repo path {settings.repo_path} not found on host")
				data = json.loads(result.out)
				data["containers"] = _normalise_containers(data.get("containers") or [])
				data["docker_df"] = _normalise_docker_df(data.get("docker_df") or [])
				self._data = data
				self._error = None
			except json.JSONDecodeError:
				self._error = "host returned unparseable output (see container log)"
				print(f"[ops] stats parse failure, raw output:\n{result.out[:2000]}", flush=True)
			except Exception as exc:
				self._error = str(exc)
			self._fetched_at = time.time()
			return self._snapshot()

	def _snapshot(self) -> dict[str, Any]:
		data = dict(self._data)
		data["_fetched_at"] = self._fetched_at
		data["_error"] = self._error
		return data


class DiskDetailCache:
	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._data: dict[str, Any] = {}
		self._fetched_at = 0.0

	async def get(self, conn: HostConnection, force: bool = False) -> dict[str, Any]:
		async with self._lock:
			fresh = self._data and time.time() - self._fetched_at < DISK_DETAIL_TTL
			if not force and fresh:
				return dict(self._data, _fetched_at=self._fetched_at)
			try:
				result = await asyncio.to_thread(conn.run, _render(DISK_DETAIL_SCRIPT), 180)
				payload = json.loads(result.out.strip() or "{}")
				count, _, size = (payload.get("pj") or "0 0").partition(" ")
				self._data = {
					"pj_count": int(count or 0),
					"pj_bytes": int(size.strip() or 0),
					"sites_bytes": int(payload.get("sites_bytes") or 0),
				}
			except Exception as exc:
				self._data = {"error": str(exc)}
			self._fetched_at = time.time()
			return dict(self._data, _fetched_at=self._fetched_at)


cache = StatsCache()
disk_detail = DiskDetailCache()
