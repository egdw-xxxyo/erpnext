#!/usr/bin/env python3
"""Shared union of the asset files of the last few releases.

Each release serves its own assets from its own image. Two requests fall outside
that: a browser tab loaded before a deploy asks for the previous release's hashed
bundles, and while two releases run side by side either may be asked for the
other's. The frontend sends a 404 from the active release here.

    publish_union.py publish            copy this image's files in, record the list
    publish_union.py gc [--keep N]      drop files no kept release lists

node_modules is left out: it is most of the tree and none of it is versioned by
name, so a copy would only ever shadow the release's own.
"""

import json
import os
import sys
import tempfile

BAKED = "/home/frappe/frappe-bench/assets"
UNION = "/home/frappe/frappe-bench/sites/assets-union"
FILES = os.path.join(UNION, "assets")
RELEASES = os.path.join(UNION, ".releases")
SKIP_DIRS = {"node_modules"}
SKIP_FILES = {"assets.json", "assets-rtl.json"}


def write_atomic(path, write):
	fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
	try:
		with os.fdopen(fd, "wb") as out:
			write(out)
		os.chmod(tmp, 0o644)
		os.replace(tmp, path)
	except BaseException:
		if os.path.exists(tmp):
			os.unlink(tmp)
		raise


def copy_file(src, dest):
	def write(out):
		with open(src, "rb") as source:
			while chunk := source.read(1 << 20):
				out.write(chunk)

	write_atomic(dest, write)


def publish():
	release = os.environ.get("ERPNEXT_RELEASE") or "unknown"
	os.makedirs(FILES, exist_ok=True)
	os.makedirs(RELEASES, exist_ok=True)

	listed, copied = [], 0
	for root, dirs, files in os.walk(BAKED, followlinks=True):
		dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
		for name in files:
			src = os.path.join(root, name)
			rel = os.path.relpath(src, BAKED)
			if rel in SKIP_FILES:
				continue
			listed.append(rel)
			dest = os.path.join(FILES, rel)
			try:
				if os.path.getsize(dest) == os.path.getsize(src):
					continue
			except OSError:
				pass
			os.makedirs(os.path.dirname(dest), exist_ok=True)
			copy_file(src, dest)
			copied += 1

	write_atomic(
		os.path.join(RELEASES, f"{release}.json"),
		lambda out: out.write(json.dumps(sorted(listed)).encode()),
	)
	print(f"asset union: release {release}, {len(listed)} files, {copied} copied")


def gc(keep):
	try:
		lists = [os.path.join(RELEASES, name) for name in os.listdir(RELEASES) if name.endswith(".json")]
	except FileNotFoundError:
		return
	lists.sort(key=os.path.getmtime, reverse=True)
	if not lists:
		return

	wanted = set()
	for path in lists[:keep]:
		with open(path) as source:
			wanted.update(json.load(source))

	removed = 0
	for root, dirs, files in os.walk(FILES, topdown=False):
		for name in files:
			path = os.path.join(root, name)
			if os.path.relpath(path, FILES) not in wanted:
				os.unlink(path)
				removed += 1
		for name in dirs:
			try:
				os.rmdir(os.path.join(root, name))
			except OSError:
				pass
	for path in lists[keep:]:
		os.unlink(path)
	print(f"asset union: kept {min(keep, len(lists))} releases, removed {removed} files")


if __name__ == "__main__":
	command = sys.argv[1] if len(sys.argv) > 1 else ""
	if command == "publish":
		publish()
	elif command == "gc":
		keep = int(sys.argv[sys.argv.index("--keep") + 1]) if "--keep" in sys.argv else 3
		gc(max(keep, 1))
	else:
		sys.exit(__doc__)
