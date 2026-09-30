"""One read-only picture of the device setup: scanners, OTDR benches, printers, scripts, commands.

Everything a supervisor would otherwise click through six DocTypes to piece together, plus
the live part that is not in the database at all — each scanner's state frame and last
activity, which live in Redis. Reads only: the state frame is read raw, so an expired frame
is reported as expired instead of being cleared the way the scan path does.
"""

import json
import re
import time

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.devices.doctype.scanner.scanner_api import _last_active_key, _state_key
from erpnext.devices.doctype.workplace_script.workplace_script import (
	_resolve_default_snapshot,
	script_for_workplace,
)

VIEW_ROLES = ("Device Manager", "Manufacturing Manager", "Manufacturing User", "System Manager")
DEFAULT_STATE_TIMEOUT = 300
DEFAULT_IDLE_TIMEOUT = 3600
BARCODE_LITERAL = re.compile(r"[\"']((?:CMD|PKG|WP|EMP)-[A-Za-z0-9_-]+)[\"']")


@frappe.whitelist()
def get_overview():
	frappe.only_for(VIEW_ROLES)

	commands = _commands()
	templates = _packing_templates()
	printers = _printers()
	scripts = _scripts()
	workplaces = _workplaces()
	libraries = _libraries()
	scanners = _scanners(workplaces)
	otdr = _otdr(workplaces)

	for wp in workplaces:
		wp["scanners"] = [s["name"] for s in scanners if s["workplace"] == wp["name"]]
	for printer in printers:
		printer["workplaces"] = [
			wp["name"]
			for wp in workplaces
			if any(p["label_printer"] == printer["name"] for p in wp["printers"])
		]
	_link_commands(commands, scripts, libraries)

	return {
		"generated_at": frappe.utils.now(),
		"default_script": script_for_workplace(None),
		"scanners": scanners,
		"workplaces": workplaces,
		"printers": printers,
		"scripts": scripts,
		"libraries": libraries,
		"commands": commands,
		"packing_templates": templates,
		"otdr": otdr,
		"issues": _sorted_issues(
			_issues(scanners, workplaces, printers, scripts, commands, templates) + _otdr_issues(otdr)
		),
	}


def _scanners(workplaces):
	rows = frappe.get_all(
		"Scanner",
		fields=["name", "scanner_name", "is_active", "workplace", "employee", "scanner_configuration"],
		order_by="name asc",
	)
	configs = {
		c.name: c
		for c in frappe.get_all(
			"Scanner Configuration", fields=["name", "state_timeout", "idle_timeout", "display_rows"]
		)
	}
	employee_names = dict(
		frappe.get_all(
			"Employee",
			filters={"name": ["in", [r.employee for r in rows if r.employee] or [""]]},
			fields=["name", "employee_name"],
			as_list=True,
		)
	)
	last_scans = _last_scans([r.name for r in rows])
	script_by_workplace = {wp["name"]: wp["script"] for wp in workplaces}
	now = time.time()

	out = []
	for row in rows:
		config = configs.get(row.scanner_configuration) or frappe._dict()
		state_timeout = cint(config.state_timeout) or DEFAULT_STATE_TIMEOUT
		idle_timeout = cint(config.idle_timeout) or DEFAULT_IDLE_TIMEOUT
		frame = _read_frame(row.name)
		last_active = _read_float(_last_active_key(row.name))

		state_age = now - frame.get("updated_at", 0) if frame else None
		frame_live = bool(frame) and state_age <= state_timeout
		idle = now - last_active if last_active else None
		active_script = (frame.get("subflow") if frame else None) or script_by_workplace.get(row.workplace)

		out.append(
			{
				"name": row.name,
				"label": row.scanner_name or row.name,
				"is_active": cint(row.is_active),
				"workplace": row.workplace,
				"employee": row.employee,
				"employee_name": employee_names.get(row.employee),
				"configuration": row.scanner_configuration,
				"script": script_by_workplace.get(row.workplace),
				"subflow": frame.get("subflow") if frame_live else None,
				"state": frame.get("state") if frame_live else None,
				"state_label": _state_label(active_script, frame.get("state")) if frame_live else None,
				"context": _short_context(frame.get("context")) if frame_live else None,
				"state_expired": bool(frame) and not frame_live,
				"state_age": int(state_age) if state_age is not None else None,
				"state_timeout": state_timeout,
				"last_active_ago": int(idle) if idle is not None else None,
				"idle_timeout": idle_timeout,
				"online": idle is not None and idle <= idle_timeout,
				"last_scan": last_scans.get(row.name),
			}
		)
	return out


def _read_frame(scanner_name):
	raw = frappe.cache().get_value(_state_key(scanner_name))
	if not raw:
		return None
	try:
		return json.loads(raw)
	except Exception:
		return None


def _read_float(key):
	raw = frappe.cache().get_value(key)
	try:
		return float(raw) if raw else None
	except (TypeError, ValueError):
		return None


def _short_context(context):
	if not context:
		return None
	out = {}
	for key, value in context.items():
		if isinstance(value, list):
			out[key] = _("{0} items").format(len(value))
		elif isinstance(value, dict):
			out[key] = "{…}"
		else:
			text = str(value)
			out[key] = text if len(text) <= 60 else text[:57] + "…"
	return out


def _last_scans(scanner_names):
	if not scanner_names:
		return {}
	rows = frappe.db.sql(
		"""
		select l.parent, l.timestamp, l.raw_data, l.status, l.result_message, l.error_message
		from `tabScanner Scan Log Entry` l
		join (
			select parent, max(idx) as idx from `tabScanner Scan Log Entry`
			where parenttype = 'Scanner' and parentfield = 'scan_logs' and parent in %(names)s
			group by parent
		) last on last.parent = l.parent and last.idx = l.idx
		where l.parenttype = 'Scanner' and l.parentfield = 'scan_logs'
		""",
		{"names": tuple(scanner_names)},
		as_dict=True,
	)
	return {r.parent: r for r in rows}


def _state_label(script_name, state_name):
	if not script_name or not state_name:
		return None
	for row in _snapshot(script_name).get("states") or []:
		if row.get("state") == state_name:
			return row.get("label") or None
	return None


def _snapshot(script_name):
	cache = frappe.flags.setdefault("device_overview_snapshots", {})
	if script_name not in cache:
		try:
			cache[script_name] = _resolve_default_snapshot(
				frappe.get_cached_doc("Workplace Script", script_name)
			)
		except Exception:
			cache[script_name] = {}
	return cache[script_name]


def _workplaces():
	rows = frappe.get_all(
		"Workplace",
		fields=["name", "barcode", "is_active", "otdr_configuration"],
		order_by="name asc",
	)
	printer_rows = frappe.get_all(
		"Workplace Printer",
		filters={"parenttype": "Workplace", "parentfield": "printers"},
		fields=["parent", "label_printer", "purpose", "is_default"],
		order_by="idx asc",
	)
	out = []
	for row in rows:
		script = script_for_workplace(row.name, include_default=0)
		out.append(
			{
				"name": row.name,
				"barcode": row.barcode,
				"is_active": cint(row.is_active),
				"script": script,
				"uses_default_script": not script,
				"otdr_configuration": row.otdr_configuration,
				"printers": [
					{"label_printer": p.label_printer, "purpose": p.purpose, "is_default": cint(p.is_default)}
					for p in printer_rows
					if p.parent == row.name
				],
			}
		)
	return out


def _printers():
	rows = frappe.get_all(
		"Label Printer",
		fields=[
			"name",
			"printer_model",
			"ip_address",
			"port",
			"is_enabled",
			"mock_printing",
			"loaded_label_size",
			"is_label_change_in_progress",
			"last_status",
			"last_checked",
		],
		order_by="name asc",
	)
	since = frappe.utils.add_to_date(None, hours=-24)
	jobs = frappe.get_all(
		"Print Job",
		filters={"creation": [">=", since]},
		fields=["label_printer", "status", {"COUNT": "*", "as": "n"}],
		group_by="label_printer, status",
	)
	counts = {}
	for job in jobs:
		counts.setdefault(job.label_printer, {})[job.status] = job.n
	for row in rows:
		row["is_enabled"] = cint(row.is_enabled)
		row["mock_printing"] = cint(row.mock_printing)
		row["jobs_24h"] = counts.get(row.name, {})
	return rows


def _scripts():
	rows = frappe.get_all(
		"Workplace Script",
		fields=[
			"name",
			"is_active",
			"parent_script",
			"default_version",
			"requires_printer",
			"printer_purpose",
			"printer_label_template",
		],
		order_by="name asc",
	)
	links = frappe.get_all(
		"Workplace Script Workplace",
		filters={"parenttype": "Workplace Script", "parentfield": "workplaces"},
		fields=["parent", "workplace"],
		order_by="idx asc",
	)
	entries = frappe.get_all(
		"Workplace Script Subflow Entry",
		filters={"parenttype": "Workplace Script", "parentfield": "subflow_entries"},
		fields=["parent", "from_state", "trigger_type", "trigger_value", "target_subflow", "description"],
		order_by="idx asc",
	)

	out = []
	for row in rows:
		snap = _snapshot(row.name)
		code = [snap.get("script") or ""] + [s.get("on_enter_script") or "" for s in snap.get("states") or []]
		out.append(
			{
				"name": row.name,
				"is_active": cint(row.is_active),
				"parent_script": row.parent_script,
				"default_version": row.default_version,
				"requires_printer": cint(row.requires_printer),
				"printer_purpose": row.printer_purpose,
				"printer_label_template": row.printer_label_template,
				"workplaces": [link.workplace for link in links if link.parent == row.name],
				"states": [
					{
						"state": s.get("state"),
						"label": s.get("label"),
						"is_initial": cint(s.get("is_initial")),
						"is_final": cint(s.get("is_final")),
					}
					for s in snap.get("states") or []
				],
				"transitions": snap.get("transitions") or [],
				"subflow_entries": [
					{
						k: e[k]
						for k in (
							"from_state",
							"trigger_type",
							"trigger_value",
							"target_subflow",
							"description",
						)
					}
					for e in entries
					if e.parent == row.name
				],
				"barcode_literals": sorted(set(BARCODE_LITERAL.findall("\n".join(code)))),
			}
		)
	return out


def _commands():
	rows = frappe.get_all(
		"Scanner Command", fields=["name", "barcode_id", "description"], order_by="barcode_id asc"
	)
	for row in rows:
		row["used_in"] = []
	return rows


def _libraries():
	from erpnext.devices.doctype.device_script.device_script import get_active_scripts

	return [
		{
			"name": lib.script_name,
			"namespace": lib.script_name.lower().replace(" ", "_").replace("-", "_"),
			"barcode_literals": sorted(set(BARCODE_LITERAL.findall(lib.script or ""))),
		}
		for lib in get_active_scripts("Scanner")
	]


def _link_commands(commands, scripts, libraries):
	by_barcode = {c["barcode_id"]: c for c in commands}
	for script in scripts:
		for entry in script["subflow_entries"]:
			if entry["trigger_type"] == "Command" and entry["trigger_value"] in by_barcode:
				by_barcode[entry["trigger_value"]]["used_in"].append(
					{"script": script["name"], "how": "subflow", "target": entry["target_subflow"]}
				)
		for literal in script["barcode_literals"]:
			if literal in by_barcode:
				by_barcode[literal]["used_in"].append({"script": script["name"], "how": "code"})
	for lib in libraries:
		for literal in lib["barcode_literals"]:
			if literal in by_barcode:
				by_barcode[literal]["used_in"].append(
					{"script": f"scripts.{lib['namespace']}", "how": "library"}
				)


def _packing_templates():
	return frappe.get_all(
		"Packing Template",
		fields=["name", "barcode_id", "is_active", "label_template", "operation"],
		order_by="name asc",
	)


OTDR_RECENT = 25


def _otdr(workplaces):
	since = frappe.utils.add_to_date(None, hours=-24)
	counts = {}
	for row in frappe.get_all(
		"OTDR Measurement",
		filters={"creation": [">=", since]},
		fields=["workplace", "status", "verdict", {"COUNT": "*", "as": "n"}],
		group_by="workplace, status, verdict",
	):
		bucket = "Error" if row.status == "Error" else (row.verdict or "Undetermined")
		per = counts.setdefault(row.workplace, {})
		per[bucket] = per.get(bucket, 0) + row.n

	fields = [
		"name",
		"creation",
		"measurement_type",
		"workplace",
		"employee",
		"serial_no",
		"item_code",
		"verdict",
		"status",
		"loss_db",
		"error_message",
		"print_job",
	]
	last_names = [
		r[0]
		for r in frappe.db.sql(
			"""
			select m.name from `tabOTDR Measurement` m
			join (
				select workplace, max(creation) as creation from `tabOTDR Measurement`
				where ifnull(workplace, '') != '' group by workplace
			) last on last.workplace = m.workplace and last.creation = m.creation
			"""
		)
	]
	last_rows = frappe.get_all(
		"OTDR Measurement", filters={"name": ["in", last_names or [""]]}, fields=fields
	)
	recent = frappe.get_all("OTDR Measurement", fields=fields, order_by="creation desc", limit=OTDR_RECENT)

	employees = {r.employee for r in last_rows + recent if r.employee}
	employee_names = dict(
		frappe.get_all(
			"Employee",
			filters={"name": ["in", list(employees) or [""]]},
			fields=["name", "employee_name"],
			as_list=True,
		)
	)
	for row in last_rows + recent:
		row["employee_name"] = employee_names.get(row.employee)
		row["error_message"] = (row.error_message or "")[:200]
	last_by_workplace = {r.workplace: r for r in last_rows}

	configs = frappe.get_all(
		"OTDR Configuration",
		fields=[
			"name",
			"device_filter",
			"sync_folder",
			"simple_sync",
			"passed_label_template",
			"failed_label_template",
		],
		order_by="name asc",
	)
	for config in configs:
		config["simple_sync"] = cint(config.simple_sync)
		config["workplaces"] = [w["name"] for w in workplaces if w["otdr_configuration"] == config.name]

	stations = [
		{
			"workplace": w["name"],
			"is_active": w["is_active"],
			"configuration": w["otdr_configuration"],
			"printers": [p["label_printer"] for p in w["printers"]],
			"counts_24h": counts.get(w["name"], {}),
			"last": last_by_workplace.get(w["name"]),
		}
		for w in workplaces
		if w["otdr_configuration"] or w["name"] in last_by_workplace
	]
	return {"stations": stations, "configurations": configs, "recent": recent}


def _otdr_issues(otdr):
	issues = []

	def add(level, message, doctype, name):
		issues.append(
			{"level": level, "area": _("OTDR"), "message": message, "doctype": doctype, "name": name}
		)

	for station in otdr["stations"]:
		if not station["is_active"]:
			continue
		if station["configuration"] and not station["printers"]:
			add(
				"warning",
				_("OTDR workplace {0} has no printer, measurement labels will not print").format(
					station["workplace"]
				),
				"Workplace",
				station["workplace"],
			)
		if not station["configuration"] and station["counts_24h"]:
			add(
				"info",
				_("Workplace {0} measures without an OTDR Configuration and uses default settings").format(
					station["workplace"]
				),
				"Workplace",
				station["workplace"],
			)
		errors = station["counts_24h"].get("Error")
		if errors:
			add(
				"warning",
				_("Workplace {0}: {1} measurements failed to process in 24 hours").format(
					station["workplace"], errors
				),
				"Workplace",
				station["workplace"],
			)

	for config in otdr["configurations"]:
		if not config["workplaces"]:
			add(
				"info",
				_("OTDR Configuration {0} is not used by any workplace").format(config.name),
				"OTDR Configuration",
				config.name,
			)
			continue
		if not config.passed_label_template or not config.failed_label_template:
			add(
				"warning",
				_("OTDR Configuration {0} has no label template for passed or failed spools").format(
					config.name
				),
				"OTDR Configuration",
				config.name,
			)
	return issues


def _issues(scanners, workplaces, printers, scripts, commands, templates):
	issues = []

	def add(level, area, message, doctype=None, name=None):
		issues.append({"level": level, "area": area, "message": message, "doctype": doctype, "name": name})

	scripts_by_name = {s["name"]: s for s in scripts}
	printers_by_name = {p["name"]: p for p in printers}
	workplaces_by_name = {w["name"]: w for w in workplaces}
	command_barcodes = {c["barcode_id"] for c in commands}
	template_barcodes = {t.barcode_id for t in templates if t.barcode_id}
	active_template_barcodes = {t.barcode_id for t in templates if t.barcode_id and t.is_active}
	workplace_barcodes = {w["barcode"] for w in workplaces if w["barcode"]}

	for s in scanners:
		if not s["is_active"]:
			continue
		if not s["workplace"]:
			add(
				"info",
				_("Scanner"),
				_("Scanner {0} has no workplace").format(s["label"]),
				"Scanner",
				s["name"],
			)
		if not s["configuration"]:
			add(
				"warning",
				_("Scanner"),
				_("Scanner {0} has no configuration").format(s["label"]),
				"Scanner",
				s["name"],
			)
		last = s["last_scan"]
		if last and last.status == "Error":
			add(
				"error",
				_("Scanner"),
				_("Last scan on {0} failed: {1}").format(s["label"], last.error_message or last.raw_data),
				"Scanner",
				s["name"],
			)

	for wp in workplaces:
		if not wp["is_active"]:
			continue
		script = scripts_by_name.get(wp["script"]) if wp["script"] else None
		if not wp["script"]:
			add(
				"info",
				_("Workplace"),
				_("Workplace {0} has no script of its own and uses the default script").format(wp["name"]),
				"Workplace",
				wp["name"],
			)
		if not wp["barcode"]:
			add(
				"warning",
				_("Workplace"),
				_("Workplace {0} has no barcode").format(wp["name"]),
				"Workplace",
				wp["name"],
			)
		if script and script["requires_printer"] and not wp["printers"]:
			add(
				"error",
				_("Workplace"),
				_("Script {0} prints, but workplace {1} has no printer").format(script["name"], wp["name"]),
				"Workplace",
				wp["name"],
			)
		for p in wp["printers"]:
			printer = printers_by_name.get(p["label_printer"])
			if printer and not printer["is_enabled"]:
				add(
					"warning",
					_("Printer"),
					_("Printer {0} at workplace {1} is disabled").format(printer["name"], wp["name"]),
					"Label Printer",
					printer["name"],
				)

	for printer in printers:
		failed = printer["jobs_24h"].get("Failed")
		if failed:
			add(
				"warning",
				_("Printer"),
				_("Printer {0}: {1} failed print jobs in 24 hours").format(printer["name"], failed),
				"Label Printer",
				printer["name"],
			)
		if printer["is_enabled"] and printer["last_status"] in ("Offline", "Connection Error"):
			add(
				"warning",
				_("Printer"),
				_("Printer {0} was offline at the last check").format(printer["name"]),
				"Label Printer",
				printer["name"],
			)

	for script in scripts:
		if not script["is_active"]:
			for wp_name in script["workplaces"]:
				if wp_name in workplaces_by_name:
					add(
						"warning",
						_("Script"),
						_("Inactive script {0} is still linked to workplace {1}").format(
							script["name"], wp_name
						),
						"Workplace Script",
						script["name"],
					)
			continue
		parent = scripts_by_name.get(script["parent_script"]) if script["parent_script"] else None
		if parent and not parent["is_active"]:
			add(
				"warning",
				_("Script"),
				_("Flow {0} belongs to inactive script {1}").format(script["name"], parent["name"]),
				"Workplace Script",
				script["name"],
			)
		if not script["states"]:
			add(
				"warning",
				_("Script"),
				_("Script {0} has no states").format(script["name"]),
				"Workplace Script",
				script["name"],
			)
		for entry in script["subflow_entries"]:
			if entry["trigger_type"] == "Command" and entry["trigger_value"] not in command_barcodes:
				add(
					"error",
					_("Script"),
					_(
						"Script {0} opens flow {1} with command {2}, but no such Scanner Command exists"
					).format(script["name"], entry["target_subflow"], entry["trigger_value"]),
					"Workplace Script",
					script["name"],
				)
			target = scripts_by_name.get(entry["target_subflow"])
			if not target:
				add(
					"error",
					_("Script"),
					_("Script {0} points to missing flow {1}").format(
						script["name"], entry["target_subflow"]
					),
					"Workplace Script",
					script["name"],
				)
			elif not target["is_active"]:
				add(
					"warning",
					_("Script"),
					_("Script {0} points to inactive flow {1}").format(script["name"], target["name"]),
					"Workplace Script",
					script["name"],
				)
		for literal in script["barcode_literals"]:
			prefix = literal.split("-", 1)[0]
			missing = (
				(prefix == "CMD" and literal not in command_barcodes)
				or (prefix == "PKG" and literal not in template_barcodes)
				or (prefix == "WP" and literal not in workplace_barcodes)
			)
			if missing:
				add(
					"error",
					_("Script"),
					_("Script {0} uses barcode {1}, which does not exist").format(script["name"], literal),
					"Workplace Script",
					script["name"],
				)
			elif prefix == "PKG" and literal not in active_template_barcodes:
				add(
					"warning",
					_("Script"),
					_("Script {0} uses packing template {1}, which is inactive").format(
						script["name"], literal
					),
					"Workplace Script",
					script["name"],
				)

	for c in commands:
		if not c["used_in"] and c["barcode_id"] != "CMD-RESET":
			add(
				"info",
				_("Command"),
				_("Command {0} is not used by any script").format(c["barcode_id"]),
				"Scanner Command",
				c["name"],
			)

	return issues


def _sorted_issues(issues):
	order = {"error": 0, "warning": 1, "info": 2}
	return sorted(issues, key=lambda i: order[i["level"]])
