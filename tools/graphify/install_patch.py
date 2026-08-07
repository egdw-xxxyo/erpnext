#!/usr/bin/env python3
"""Install the DocType JSON extractor into the graphify tool venv.

Graphify has no plugin seam, so this monkeypatches ``graphify.extract._DISPATCH``
at interpreter startup via a ``sitecustomize.py`` dropped in the tool venv.
Nothing inside the graphify package is edited, so ``uv tool upgrade graphifyy``
does not clobber it — but re-run this script after an upgrade anyway to pick up
a refreshed stock extractor.

Usage:
    python3 tools/graphify/install_patch.py           # install
    python3 tools/graphify/install_patch.py --check   # verify only
    python3 tools/graphify/install_patch.py --remove  # uninstall
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

MARKER = "# >>> erpnext graphify doctype extractor >>>"
MARKER_END = "# <<< erpnext graphify doctype extractor <<<"
MODULE_NAME = "erpnext_graphify_doctype"

SITECUSTOMIZE_BLOCK = f"""{MARKER}
try:
    import {MODULE_NAME}
    {MODULE_NAME}.install()
except Exception:  # never break the interpreter over an optional patch
    pass
{MARKER_END}
"""

INSTALL_HOOK = '''

def install():
    """Patch graphify's .json dispatch to understand Frappe DocType JSON."""
    import graphify.extract as _extract

    current = _extract._DISPATCH.get(".json")
    if getattr(current, "_erpnext_doctype_patched", False):
        return
    patched = make_json_extractor(current)
    patched._erpnext_doctype_patched = True
    _extract._DISPATCH[".json"] = patched
'''


def graphify_site_packages() -> Path:
	exe = shutil.which("graphify")
	if not exe:
		sys.exit("graphify not on PATH — run: uv tool install graphifyy")
	shebang = Path(exe).read_text(encoding="utf-8", errors="replace").splitlines()[0]
	if not shebang.startswith("#!"):
		sys.exit(f"cannot read interpreter from {exe}")
	python = shebang[2:].strip()
	out = subprocess.run(
		[python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
		capture_output=True,
		text=True,
		check=True,
	)
	return Path(out.stdout.strip())


def do_install(site_packages: Path) -> None:
	source = Path(__file__).with_name("doctype_json.py").read_text(encoding="utf-8")
	(site_packages / f"{MODULE_NAME}.py").write_text(source + INSTALL_HOOK, encoding="utf-8")

	sitecustomize = site_packages / "sitecustomize.py"
	existing = sitecustomize.read_text(encoding="utf-8") if sitecustomize.exists() else ""
	if MARKER in existing:
		print("sitecustomize.py: block already present")
	else:
		sitecustomize.write_text(
			(existing + "\n" if existing else "") + SITECUSTOMIZE_BLOCK, encoding="utf-8"
		)
		print(f"sitecustomize.py: block added ({sitecustomize})")
	print(f"module installed: {site_packages / (MODULE_NAME + '.py')}")


def do_remove(site_packages: Path) -> None:
	module = site_packages / f"{MODULE_NAME}.py"
	if module.exists():
		module.unlink()
		print(f"removed {module}")
	sitecustomize = site_packages / "sitecustomize.py"
	if sitecustomize.exists():
		text = sitecustomize.read_text(encoding="utf-8")
		if MARKER in text and MARKER_END in text:
			head, _, rest = text.partition(MARKER)
			_, _, tail = rest.partition(MARKER_END)
			sitecustomize.write_text((head + tail).strip() + "\n", encoding="utf-8")
			print("removed block from sitecustomize.py")


def do_check(site_packages: Path) -> int:
	exe = shutil.which("graphify")
	shebang = Path(exe).read_text(encoding="utf-8", errors="replace").splitlines()[0]
	python = shebang[2:].strip()
	probe = (
		"import graphify.extract as e; "
		"f = e._DISPATCH['.json']; "
		"print('PATCHED' if getattr(f, '_erpnext_doctype_patched', False) else 'STOCK')"
	)
	out = subprocess.run([python, "-c", probe], capture_output=True, text=True)
	status = (out.stdout or out.stderr).strip()
	print(f"json extractor: {status}")
	return 0 if status == "PATCHED" else 1


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--check", action="store_true")
	parser.add_argument("--remove", action="store_true")
	args = parser.parse_args()

	site_packages = graphify_site_packages()
	if args.remove:
		do_remove(site_packages)
		return 0
	if args.check:
		return do_check(site_packages)
	do_install(site_packages)
	return do_check(site_packages)


if __name__ == "__main__":
	raise SystemExit(main())
