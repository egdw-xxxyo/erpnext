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

from .ssh import HostConnection

TREE_TTL = 600.0
MAX_ROWS = 200
SCAN_TIMEOUT = 300

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9_./ @+:,=~-]*$")

SCRIPT = r"""
P=@PATH@
[ -d "$P" ] || exit 91
du -xak --max-depth=1 -- "$P" 2>/dev/null | while IFS=$'\t' read -r s p; do
  if [ -d "$p" ] && [ ! -L "$p" ]; then t=d; else t=f; fi
  printf '%s\t%s\t%s\n' "$s" "$t" "$p"
done
"""


def valid_path(path: str) -> bool:
	return bool(_SAFE_PATH.match(path)) and ".." not in path.split("/") and len(path) <= 512


def _parse(out: str, path: str) -> dict[str, Any]:
	total = 0
	rows: list[dict[str, Any]] = []
	for line in out.splitlines():
		parts = line.split("\t", 2)
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
	return {"total": total, "rows": rows[:MAX_ROWS], "hidden": max(len(rows) - MAX_ROWS, 0)}


class SpaceTreeCache:
	def __init__(self) -> None:
		self._lock = asyncio.Lock()
		self._data: dict[str, tuple[float, dict[str, Any]]] = {}

	async def get(self, conn: HostConnection, path: str, force: bool = False) -> dict[str, Any]:
		async with self._lock:
			hit = self._data.get(path)
			if not force and hit and time.time() - hit[0] < TREE_TTL:
				return dict(hit[1], _fetched_at=hit[0])
			result = await asyncio.to_thread(
				conn.run, SCRIPT.replace("@PATH@", shlex.quote(path)), SCAN_TIMEOUT
			)
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
