"""Report DocTypes that exist only in the site database.

DocTypes created through the desk UI carry ``custom = 1`` and live nowhere but
this site's database — they do not travel in the Docker image and are absent
from git. Prototyping that way is fine; forgetting about it is not. ``./deploy``
prints this table after every migrate so long-lived prototypes stay visible.

Advisory only: it never fails a deploy. Graduate a DocType with ``./codify``.
"""

import os

import frappe
from frappe.modules import scrub


def find_on_disk(doctype: str) -> str | None:
	"""Path of the DocType's JSON in any installed app, or None if DB-only."""
	snake = scrub(doctype)
	for app in frappe.get_installed_apps():
		app_path = frappe.get_app_path(app)
		for module in os.listdir(app_path):
			candidate = os.path.join(app_path, module, "doctype", snake, f"{snake}.json")
			if os.path.exists(candidate):
				return candidate
	return None


def _count(d) -> int:
	"""Row count, or 0 for the DocTypes that have no table of their own."""
	if d.issingle or d.is_virtual:
		return 0
	try:
		return frappe.db.count(d.name)
	except Exception:
		return 0


def collect() -> list[dict]:
	rows = []
	for d in frappe.get_all(
		"DocType",
		filters={"custom": 1},
		fields=["name", "module", "istable", "issingle", "is_virtual", "creation"],
		order_by="creation asc",
	):
		path = find_on_disk(d.name)
		rows.append(
			{
				"name": d.name,
				"module": d.module,
				"istable": bool(d.istable),
				"documents": _count(d),
				"age_days": (frappe.utils.now_datetime() - d.creation).days,
				"in_repo": bool(path),
			}
		)
	return rows


def report() -> None:
	"""Print the drift table. Always exits cleanly, drift or not."""
	rows = collect()
	drifting = [r for r in rows if not r["in_repo"]]
	if not drifting:
		print("DocType drift: none — every custom DocType is backed by repo files.")
		return

	width = max(len(r["name"]) for r in drifting)
	print(f"DocType drift: {len(drifting)} DocType(s) exist only in this site's database.")
	print('Graduate one with:  ./codify export "<DocType>" --module <stock module> --env <env>')
	for r in sorted(drifting, key=lambda r: -r["age_days"]):
		kind = "child" if r["istable"] else "doc"
		print(
			f"  {r['name']:<{width}}  {r['module']:<22} {kind:<6} "
			f"{r['documents']:>6} docs  {r['age_days']:>4}d  NOT IN REPO"
		)
