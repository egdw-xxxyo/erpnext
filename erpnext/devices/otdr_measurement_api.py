# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The API the measuring phone talks to.

Replaces `otdr_api`, which was built around an `OTDR` document standing for "which device
is this". That identity existed to carry API keys handed out by QR pairing; the app now
logs in with a password and holds a session, so the device no longer needs a name. What
the server actually needs to know is **which bench** the work is happening at — that
decides the quality rules, the printer, and the script — so `workplace` is the scoping
argument everywhere here.

Endpoints are session-authenticated. None of them is `allow_guest`.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.devices.sor_parser import flatten_measurement, parse_sor_file
from erpnext.devices.workplace_dispatch import dispatch_measurement

MANAGER_ROLES = ("Manufacturing Manager", "Device Manager", "System Manager")


def _session_employee():
	"""The Employee for the logged-in user, or None."""
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")


def _assert_workplace_allowed(workplace, employee):
	"""A user may measure at a workplace they are assigned to.

	Managers are exempt so a supervisor can reproduce a bench problem without being added
	to the roster. Everyone else must appear in `Workplace.allowed_employees` — the same
	roster the scanner path honours, rather than a second list to keep in step.
	"""
	if not frappe.db.exists("Workplace", workplace):
		frappe.throw(_("Workplace {0} not found").format(workplace), frappe.DoesNotExistError)

	if any(role in frappe.get_roles() for role in MANAGER_ROLES):
		return

	allowed = frappe.db.exists(
		"Workplace Employee",
		{"parent": workplace, "parenttype": "Workplace", "employee": employee},
	)
	if not allowed:
		frappe.throw(
			_("You are not assigned to workplace {0}").format(workplace),
			frappe.PermissionError,
		)


def _attach_sor(measurement_name, filename, content):
	"""Keep the raw trace with the measurement.

	The parsed payload is stored too, but the original bytes are the only thing that can be
	re-read if the parser is ever fixed or questioned.
	"""
	try:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"attached_to_doctype": "OTDR Measurement",
				"attached_to_name": measurement_name,
				"content": content,
				"is_private": 1,
			}
		)
		file_doc.flags.ignore_permissions = True
		file_doc.insert()
		return file_doc.file_url
	except Exception:
		frappe.log_error(title="Failed to attach SOR file to measurement")
		return None


@frappe.whitelist(methods=["POST"])
def submit_measurement(
	workplace=None,
	serial_no=None,
	filename=None,
	remote_path=None,
	auto_print=None,
	label_printer=None,
	**kwargs,
):
	"""Accept raw SOR bytes (multipart `file`), grade them, answer pass/fail.

	Always records an OTDR Measurement, including when grading could not happen — an
	unreadable trace or an unknown serial is exactly the case somebody needs to look at
	later, and a record that only exists on success cannot show it.
	"""
	if not workplace:
		frappe.throw(_("Workplace is required"))

	employee = _session_employee()
	_assert_workplace_allowed(workplace, employee)

	files = frappe.request.files if frappe.request is not None else None
	f = files.get("file") if files else None
	if f is None:
		frappe.throw(_("Missing 'file' multipart field"))

	raw = f.read()
	fname = filename or getattr(f, "filename", None) or "upload.sor"

	sor_info = None
	parse_error = None
	try:
		import os
		import tempfile

		tmp = tempfile.NamedTemporaryFile(prefix="sor_", suffix=".sor", delete=False)
		tmp.write(raw)
		tmp.close()
		try:
			sor_info = parse_sor_file(tmp.name)
		finally:
			try:
				os.unlink(tmp.name)
			except Exception:
				pass
	except Exception as e:
		parse_error = f"parse failed: {e}"

	# An unknown serial must not blow up on link validation — the operator mistyped or scanned
	# the wrong code, and they need a readable answer, not an HTTP 417 with no body.
	unknown_serial = None
	if serial_no and not frappe.db.exists("Serial No", serial_no):
		unknown_serial = serial_no
		serial_no = None

	payload = {
		"filename": fname,
		"remote_path": remote_path or "",
		"size_bytes": len(raw),
		"serial_no": serial_no or unknown_serial or "",
		"workplace": workplace,
	}
	if sor_info:
		payload["sor"] = sor_info
		payload.update(flatten_measurement(sor_info))

	measurement = frappe.get_doc(
		{
			"doctype": "OTDR Measurement",
			"measurement_type": "SOR",
			"serial_no": serial_no or None,
			"workplace": workplace,
			"employee": employee,
			"measured_on": frappe.utils.now_datetime(),
			"status": "Success" if (sor_info and not unknown_serial) else "Error",
			"error_message": parse_error
			or (_("Unknown serial number: {0}").format(unknown_serial) if unknown_serial else None),
			"filename": fname,
			"remote_path": remote_path or None,
			"loss_db": payload.get("loss_db") or 0,
			"distance_km": payload.get("distance_km") or 0,
			"reflectance_db": payload.get("reflectance_db") or 0,
			"wavelength_nm": payload.get("wavelength_nm") or 0,
			"payload": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
		}
	)
	measurement.flags.ignore_permissions = True
	measurement.insert()

	sor_file_url = _attach_sor(measurement.name, fname, raw)

	if not sor_info:
		measurement.db_set({"sor_file": sor_file_url, "verdict": "Undetermined"})
		frappe.db.commit()
		return {
			"success": False,
			"error": parse_error,
			"measurement": measurement.name,
			"verdict": "Undetermined",
			"printers": _printers(workplace),
		}

	if unknown_serial:
		measurement.db_set({"sor_file": sor_file_url, "verdict": "Undetermined"})
		frappe.db.commit()
		return {
			"success": False,
			"error": _("Unknown serial number: {0}").format(unknown_serial),
			"measurement": measurement.name,
			"verdict": "Undetermined",
			"printers": _printers(workplace),
		}

	result, info = dispatch_measurement(
		workplace,
		employee=employee,
		payload=payload,
		serial_no=serial_no,
		measurement=measurement.name,
		auto_print=cint(auto_print),
		label_printer=label_printer,
	)

	summary = result if isinstance(result, dict) else {}
	verdict = summary.get("verdict") or ("Undetermined" if summary.get("status") != "ok" else None)

	measurement.db_set(
		{
			"sor_file": sor_file_url,
			"serial_no": summary.get("serial_no") or measurement.serial_no,
			"verdict": verdict,
			"quality_inspection": summary.get("quality_inspection"),
			"print_job": summary.get("print_job"),
			"script_state": info.get("state"),
			"script_log": info.get("logs"),
			"status": "Error" if info.get("error") else measurement.status,
			"error_message": info.get("error") or measurement.error_message,
		}
	)
	frappe.db.commit()

	return {
		"success": not info.get("error"),
		"error": info.get("error"),
		"measurement": measurement.name,
		"serial_no": summary.get("serial_no"),
		"item_code": summary.get("item_code"),
		"verdict": verdict,
		"reason": summary.get("reason"),
		"quality_inspection": summary.get("quality_inspection"),
		"qi_readings": _qi_readings(summary.get("quality_inspection")),
		"print_job": summary.get("print_job"),
		"state": info.get("state"),
		"log": info.get("logs"),
		"printers": _printers(workplace),
		"sor": sor_info,
	}


def _qi_readings(quality_inspection):
	"""Each graded reading with its measured value and allowed range, for the operator screen."""
	if not quality_inspection:
		return []

	rows = frappe.get_all(
		"Quality Inspection Reading",
		filters={"parent": quality_inspection, "parenttype": "Quality Inspection"},
		fields=[
			"specification",
			"reading_1",
			"min_value",
			"max_value",
			"numeric",
			"manual_inspection",
			"status",
		],
		order_by="idx asc",
	)
	return [
		{
			"specification": r.specification,
			"value": r.reading_1,
			"min_value": r.min_value if cint(r.numeric) else None,
			"max_value": r.max_value if cint(r.numeric) else None,
			"manual": bool(cint(r.manual_inspection)),
			"status": r.status,
		}
		for r in rows
	]


def _printers(workplace):
	from erpnext.devices.printer_resolution import printers_for_workplace

	return printers_for_workplace(workplace)


@frappe.whitelist(methods=["GET"])
def get_workplaces(line_type=None, production_line=None, **kwargs):
	"""Workplaces the caller may measure at, each with its printers.

	This is what fills the app's workplace picker, replacing the device-scoped item
	dropdown that `get_configuration` used to ship as `qc_items`.

	`line_type` (or a named `production_line`) narrows the list to the benches that line runs
	at — the app's OTDR tab passes "Spool", so an operator assigned to several kinds of bench
	is only offered the optics ones. A line type nobody has listed benches for is not a
	filter: the full list is returned, so a line set up before the workplace table keeps
	working.
	"""
	employee = _session_employee()
	is_manager = any(role in frappe.get_roles() for role in MANAGER_ROLES)

	if is_manager:
		names = frappe.get_all("Workplace", filters={"is_active": 1}, pluck="name")
	else:
		if not employee:
			return []
		names = frappe.get_all(
			"Workplace Employee",
			filters={"parenttype": "Workplace", "employee": employee},
			pluck="parent",
		)
		if names:
			names = frappe.get_all(
				"Workplace",
				filters={"name": ["in", names], "is_active": 1},
				pluck="name",
			)

	if line_type or production_line:
		from erpnext.manufacturing.doctype.production_line import production_line as production_line_engine

		allowed = production_line_engine.line_workplaces(line_type=line_type, production_line=production_line)
		if allowed:
			names = [name for name in names if name in allowed]

	out = []
	for name in names:
		doc = frappe.get_cached_doc("Workplace", name)
		out.append(
			{
				"name": doc.name,
				"workplace_name": doc.workplace_name,
				"short_name": doc.short_name,
				"otdr_configuration": doc.otdr_configuration,
				"printers": _printers(doc.name),
			}
		)
	return out


@frappe.whitelist(methods=["GET"])
def get_configuration(workplace=None, app_version=None, client=None, **kwargs):
	"""Sync and BLE settings for the phone working at `workplace`.

	The settings themselves still live in `OTDR Configuration` — they describe the
	reflectometer and the sync loop, which did not change. Only the thing that points at
	them moved, from the per-device OTDR record to the workplace.
	"""
	from erpnext.devices.app_version import is_app_compatible, min_version_for

	config_name = None
	if workplace:
		config_name = frappe.db.get_value("Workplace", workplace, "otdr_configuration")

	cfg = frappe.get_cached_doc("OTDR Configuration", config_name) if config_name else frappe._dict()

	extra = cfg.get("extra_config")
	if extra:
		try:
			extra = json.loads(extra)
		except Exception:
			pass

	client = client or "android"
	return {
		"workplace": workplace,
		"sync_folder": cfg.get("sync_folder") or "/otdr",
		"simple_sync": bool(cfg.get("simple_sync")),
		"measurement_interval_seconds": cfg.get("measurement_interval_seconds") or 60,
		"device_filter": cfg.get("device_filter") or "adminvasa",
		"phone_name": cfg.get("phone_name") or "",
		"scan_path": cfg.get("scan_path") or "",
		"window_hours": cfg.get("window_hours") or 2400,
		"poll_interval_s": cfg.get("poll_interval_s") or 5.0,
		"chunk_size": cfg.get("chunk_size") or 20224,
		"heartbeat_interval_s": cfg.get("heartbeat_interval_s") or 10,
		"extra_config": extra,
		"printers": _printers(workplace),
		"app_version": app_version or "",
		"app_client": client,
		"min_app_version": min_version_for(client),
		"app_compatible": is_app_compatible(app_version, client),
		"server_time": frappe.utils.now_datetime().isoformat(),
	}


def _log_simple_measurement(workplace, measurement_type, payload, **fields):
	"""Record a non-trace reading (power meter, VFL toggle).

	These used to append to the device's capped measurement log. They are kept because the
	app still offers both, but they are not graded: there is no spool, no serial and no
	quality template involved — the value of the record is the history.
	"""
	employee = _session_employee()
	_assert_workplace_allowed(workplace, employee)

	doc = frappe.get_doc(
		{
			"doctype": "OTDR Measurement",
			"measurement_type": measurement_type,
			"workplace": workplace,
			"employee": employee,
			"measured_on": frappe.utils.now_datetime(),
			"status": "Success",
			"payload": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
			**fields,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	frappe.db.commit()
	return {"success": True, "measurement": doc.name}


@frappe.whitelist(methods=["POST"])
def submit_opm_measurement(
	workplace=None,
	wavelength_nm=None,
	power_dbm=None,
	power_mw=None,
	mode=None,
	reference=None,
	raw=None,
	**kwargs,
):
	"""One optical-power-meter reading from the phone."""
	if not workplace:
		frappe.throw(_("Workplace is required"))

	payload = {
		"wavelength_nm": wavelength_nm,
		"power_dbm": power_dbm,
		"power_mw": power_mw,
		"mode": mode,
		"reference": reference,
		"raw": raw,
	}
	return _log_simple_measurement(
		workplace,
		"OPM",
		payload,
		wavelength_nm=frappe.utils.flt(wavelength_nm),
	)


@frappe.whitelist(methods=["POST"])
def submit_vfl_event(workplace=None, duty=None, **kwargs):
	"""Visual fault locator turned on or off at this bench."""
	if not workplace:
		frappe.throw(_("Workplace is required"))

	return _log_simple_measurement(workplace, "VFL", {"duty": duty})


@frappe.whitelist(methods=["POST"])
def print_measurement_label(measurement=None, label_printer=None, **kwargs):
	"""Print the label for an already-graded measurement.

	The path taken when auto-print is off, or when the bench has several printers and no
	default so the operator picks one. Grading is not repeated — the verdict on the
	measurement decides which template is used.
	"""
	if not measurement:
		frappe.throw(_("Measurement is required"))

	doc = frappe.get_doc("OTDR Measurement", measurement)
	if not doc.quality_inspection:
		frappe.throw(_("Measurement {0} has no Quality Inspection to print for").format(measurement))

	_assert_workplace_allowed(doc.workplace, _session_employee())

	from erpnext.devices.spool_qc import _get_config, print_qc_label

	qi = frappe.get_doc("Quality Inspection", doc.quality_inspection)
	otdr_configuration = frappe.db.get_value("Workplace", doc.workplace, "otdr_configuration")
	cfg = _get_config(otdr_configuration)

	try:
		payload = json.loads(doc.payload or "{}")
	except Exception:
		payload = {}

	logs: list[str] = []

	def log(message, level="INFO", **extra):
		logs.append(f"{level} {message}")

	print_job = print_qc_label(
		doc.serial_no,
		doc.item_code,
		qi,
		payload,
		otdr_configuration,
		cfg,
		log,
		workplace=doc.workplace,
		label_printer=label_printer,
	)

	if print_job:
		doc.db_set("print_job", print_job)
		frappe.db.commit()

	return {"success": bool(print_job), "print_job": print_job, "log": "\n".join(logs)}


def _printer_state(printer_name):
	row = frappe.db.get_value(
		"Label Printer",
		printer_name,
		[
			"is_enabled",
			"mock_printing",
			"loaded_label_size",
			"is_label_change_in_progress",
			"label_change_message",
			"last_status",
			"last_checked",
			"printer_model",
		],
		as_dict=True,
	)
	if not row:
		return {"name": printer_name, "exists": False}
	return {
		"name": printer_name,
		"exists": True,
		"enabled": bool(row.is_enabled),
		"mock_printing": bool(row.mock_printing),
		"loaded_label_size": row.loaded_label_size,
		"label_change_in_progress": bool(row.is_label_change_in_progress),
		"label_change_message": row.label_change_message,
		"last_status": row.last_status,
		"last_checked": str(row.last_checked) if row.last_checked else None,
		"printer_model": row.printer_model,
	}


@frappe.whitelist(methods=["GET"])
def get_label_readiness(workplace=None, item_code=None, label_printer=None, **kwargs):
	if not workplace:
		frappe.throw(_("Workplace is required"))

	_assert_workplace_allowed(workplace, _session_employee())

	from erpnext.devices.label_resolution import PURPOSE_FAILED, PURPOSE_PASSED, resolve_label_template
	from erpnext.devices.printer_resolution import resolve_printer
	from erpnext.devices.spool_qc import _any_printer_for, _get_config

	otdr_configuration = frappe.db.get_value("Workplace", workplace, "otdr_configuration")
	cfg = _get_config(otdr_configuration)

	issues = []
	if not cfg.get("print_label"):
		issues.append({"code": "printing_disabled"})
	if not item_code:
		issues.append({"code": "no_item"})

	fallback_printer = _any_printer_for(item_code) if item_code else None
	printers = {}
	labels = []

	for purpose in (PURPOSE_PASSED, PURPOSE_FAILED):
		resolved = (
			resolve_label_template(item_code, purpose, otdr_configuration=otdr_configuration)
			if item_code
			else None
		) or {}
		template = resolved.get("label_template")
		label_size = frappe.db.get_value("Label Template", template, "label_size") if template else None
		printer, _source = resolve_printer(
			workplace=workplace,
			explicit=label_printer,
			purpose=purpose,
			fallbacks=[resolved.get("label_printer"), fallback_printer],
		)
		if printer and printer not in printers:
			printers[printer] = _printer_state(printer)
		loaded = (printers.get(printer) or {}).get("loaded_label_size")

		labels.append(
			{
				"purpose": purpose,
				"label_template": template,
				"label_size": label_size,
				"source": resolved.get("source"),
				"label_printer": printer,
				"loaded_label_size": loaded,
				"size_ok": bool(label_size and loaded and label_size == loaded),
			}
		)

		if item_code and not template:
			issues.append({"code": "no_template", "purpose": purpose})
		elif template and not label_size:
			issues.append({"code": "no_template_size", "purpose": purpose, "label_template": template})
		if not printer:
			issues.append({"code": "no_printer", "purpose": purpose})
		elif label_size and loaded and label_size != loaded:
			issues.append(
				{
					"code": "size_mismatch",
					"purpose": purpose,
					"printer": printer,
					"expected": label_size,
					"loaded": loaded,
				}
			)

	for name, state in printers.items():
		if not state["exists"]:
			issues.append({"code": "printer_not_found", "printer": name})
			continue
		if not state["enabled"]:
			issues.append({"code": "printer_disabled", "printer": name})
		if state["label_change_in_progress"]:
			issues.append({"code": "label_change_in_progress", "printer": name})
		if not state["loaded_label_size"]:
			issues.append({"code": "no_loaded_size", "printer": name})

	return {
		"ready": not issues,
		"workplace": workplace,
		"item_code": item_code,
		"labels": labels,
		"printers": list(printers.values()),
		"issues": issues,
	}


@frappe.whitelist(methods=["GET"])
def get_print_job_status(print_job=None, **kwargs):
	if not print_job:
		frappe.throw(_("Print Job is required"))

	workplace = frappe.db.get_value("OTDR Measurement", {"print_job": print_job}, "workplace")
	if not workplace:
		frappe.throw(
			_("Print Job {0} does not belong to a measurement").format(print_job), frappe.DoesNotExistError
		)

	_assert_workplace_allowed(workplace, _session_employee())

	job = frappe.db.get_value(
		"Print Job",
		print_job,
		[
			"name",
			"status",
			"error_message",
			"printed_at",
			"label_printer",
			"label_template",
			"label_size",
			"creation",
		],
		as_dict=True,
	)
	if not job:
		frappe.throw(_("Print Job {0} not found").format(print_job), frappe.DoesNotExistError)

	return {
		"print_job": job.name,
		"status": job.status,
		"error_message": job.error_message,
		"printed_at": str(job.printed_at) if job.printed_at else None,
		"label_printer": job.label_printer,
		"label_template": job.label_template,
		"label_size": job.label_size,
		"age_seconds": int((frappe.utils.now_datetime() - job.creation).total_seconds()),
	}
