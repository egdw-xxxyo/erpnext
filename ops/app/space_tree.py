"""On-demand disk usage tree: one `du` level per request, cached.

The page loads the root level and each directory fetches its own children when
opened, so a scan of `/` never has to walk the whole disk in a single call.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import time
from typing import Any

from .config import settings
from .ssh import HostConnection

TREE_TTL = 600.0
MAX_ROWS = 200
SCAN_TIMEOUT = 300

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9_./ @+:,=~-]*$")

SCRIPT = r"""
P=@PATH@
[ -d "$P" ] || exit 91
E=$(mktemp)
MODE=user
if sudo -n -l -- /usr/bin/du >/dev/null 2>&1; then
  MODE=sudo
else
  IMG=$(docker compose -p @PROJECT@ -f @REPO@/docker-compose.yml ps -q backend 2>/dev/null | head -1 \
    | xargs -r docker inspect --format '{{.Image}}' 2>/dev/null)
  [ -n "$IMG" ] && MODE=docker
fi
scan() {
  case $MODE in
    sudo) sudo -n /usr/bin/du -xak --max-depth=1 -- "$P" 2>"$E" ;;
    docker)
      docker run --rm --user 0 --network none --entrypoint du -v /:/host:ro "$IMG" \
        -xak --max-depth=1 -- "/host$P" 2>"$E" | sed -E 's#\t/host#\t#; s#\t$#\t/#'
      ;;
    *) du -xak --max-depth=1 -- "$P" 2>"$E" ;;
  esac
}
scan | while IFS=$'\t' read -r s p; do
  if [ -d "$p" ] && [ ! -L "$p" ]; then t=d; else t=f; fi
  printf '%s\t%s\t%s\n' "$s" "$t" "$p"
done
printf 'ERR\t%s\t%s\n' "$(grep -c 'Permission denied' "$E")" "$MODE"
printf 'MSG\t%s\t\n' "$(grep -v 'Permission denied' "$E" | head -3 | tr '\n\t' '  ')"
rm -f "$E"
"""


def valid_path(path: str) -> bool:
	return bool(_SAFE_PATH.match(path)) and ".." not in path.split("/") and len(path) <= 512


def _parse(out: str, path: str) -> dict[str, Any]:
	total = 0
	rows: list[dict[str, Any]] = []
	denied = 0
	message = ""
	elevated = False
	mode = "user"
	for line in out.splitlines():
		parts = line.split("\t", 2)
		if parts[0] == "MSG":
			message = parts[1].strip()
			continue
		if parts[0] == "ERR" and len(parts) == 3:
			denied = int(parts[1]) if parts[1].isdigit() else 0
			mode = parts[2]
			elevated = parts[2] in ("sudo", "docker")
			continue
		if len(parts) != 3 or not parts[0].isdigit():
			continue
		size = int(parts[0]) * 1024
		if parts[2].rstrip("/") == path.rstrip("/"):
			total = size
			continue
		rows.append(
			{"bytes": size, "dir": parts[1] == "d", "path": parts[2], "name": parts[2].rsplit("/", 1)[-1]}
		)
	rows.sort(key=lambda r: r["bytes"], reverse=True)
	return {
		"total": total,
		"rows": rows[:MAX_ROWS],
		"hidden": max(len(rows) - MAX_ROWS, 0),
		"denied": denied,
		"elevated": elevated,
		"mode": mode,
		"message": message,
	}


def _render(path: str) -> str:
	return (
		SCRIPT.replace("@PATH@", shlex.quote(path))
		.replace("@PROJECT@", shlex.quote(settings.compose_project))
		.replace("@REPO@", shlex.quote(settings.repo_path))
	)


class SpaceTreeCache:
	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._data: dict[str, tuple[float, dict[str, Any]]] = {}

	async def get(self, conn: HostConnection, path: str, force: bool = False) -> dict[str, Any]:
		async with self._lock:
			hit = self._data.get(path)
			if not force and hit and time.time() - hit[0] < TREE_TTL:
				return dict(hit[1], _fetched_at=hit[0])
			result = await asyncio.to_thread(conn.run, _render(path), SCAN_TIMEOUT)
			if result.rc == 91:
				return {
					"error": f"{path} is not a directory on the host",
					"rows": [],
					"total": 0,
					"hidden": 0,
				}
			data = _parse(result.out, path)
			now = time.time()
			self._data[path] = (now, data)
			if len(self._data) > 500:
				oldest = min(self._data, key=lambda k: self._data[k][0])
				del self._data[oldest]
			return dict(data, _fetched_at=now)


space_tree = SpaceTreeCache()
