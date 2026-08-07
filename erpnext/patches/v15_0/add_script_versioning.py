import json
import os

import frappe
from frappe import get_app_path


def _reload(doctype_dir):
	for module in ("devices", "manufacturing"):
		path = os.path.join(get_app_path("erpnext", module, "doctype"), doctype_dir)
		if os.path.isdir(path):
			frappe.reload_doc(module, "doctype", doctype_dir)
			return


def execute():
	# Workplace Script moved to the Devices module; reload from wherever the JSON lives.
	_reload("workplace_script_version")
	_reload("workplace_script")
	# Scanner Script was unified into Device Script later; only reload if old folder still present (legacy installs).
	_reload("scanner_script_version")
	_reload("scanner_script")

	for name in frappe.get_all("Workplace Script", pluck="name"):
		doc = frappe.get_doc("Workplace Script", name)
		if doc.versions:
			continue
		snap = {
			"script": doc.script or "",
			"states": [
				{
					"state": s.state,
					"label": s.label,
					"is_initial": int(s.is_initial or 0),
					"is_final": int(s.is_final or 0),
					"position_x": s.position_x,
					"position_y": s.position_y,
					"on_enter_script": s.on_enter_script,
				}
				for s in (doc.states or [])
			],
			"transitions": [
				{"from_state": t.from_state, "event": t.event, "to_state": t.to_state}
				for t in (doc.transitions or [])
			],
		}
		doc.append(
			"versions",
			{
				"version": "v1",
				"is_default": 1,
				"snapshot": json.dumps(snap),
				"created_on": doc.modified,
			},
		)
		doc.default_version = "v1"
		doc.viewing_version = "v1"
		doc.save(ignore_permissions=True)

	if frappe.db.exists("DocType", "Scanner Script"):
		for name in frappe.get_all("Scanner Script", pluck="name"):
			doc = frappe.get_doc("Scanner Script", name)
			if doc.versions:
				continue
			doc.append(
				"versions",
				{
					"version": "v1",
					"is_default": 1,
					"snapshot": json.dumps({"script": doc.script or ""}),
					"created_on": doc.modified,
				},
			)
			doc.default_version = "v1"
			doc.viewing_version = "v1"
			doc.save(ignore_permissions=True)

	frappe.db.commit()
