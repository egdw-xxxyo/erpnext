"""Read and replace small config files in the repo on the host.

Content travels base64-encoded inside the script fed to ``bash -s``, so no
value ever needs shell quoting. Writes go to a temp file in the same
directory and are renamed over the target, so ./deploy never reads a half
written file; the previous version is kept next to it as ``<name>.bak``.
"""

from __future__ import annotations

import base64
import shlex

from .ssh import HostConnection

MISSING = "__OPS_MISSING__"


class HostFileError(Exception):
	pass


def read(conn: HostConnection, rel_path: str) -> str | None:
	path = shlex.quote(rel_path)
	result = conn.run_in_repo(f"if [ -f {path} ]; then base64 < {path}; else echo {MISSING}; fi", timeout=10)
	if not result.ok:
		raise HostFileError(result.err.strip() or f"could not read {rel_path}")
	out = result.out.strip()
	if out == MISSING:
		return None
	return base64.b64decode(out).decode("utf-8")


def write(conn: HostConnection, rel_path: str, content: str, mode: str = "600") -> None:
	path = shlex.quote(rel_path)
	payload = shlex.quote(base64.b64encode(content.encode("utf-8")).decode("ascii"))
	script = f"""set -e
[ -f {path} ] && cp -p {path} {path}.bak
tmp=$(mktemp {path}.XXXXXX)
printf '%s' {payload} | base64 -d > "$tmp"
chmod {mode} "$tmp"
mv -f "$tmp" {path}
"""
	result = conn.run_in_repo(script, timeout=15)
	if not result.ok:
		raise HostFileError(result.err.strip() or f"could not write {rel_path}")
