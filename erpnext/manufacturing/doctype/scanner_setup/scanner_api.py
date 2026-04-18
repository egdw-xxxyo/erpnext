import hmac
import json

import frappe
from frappe.utils import now_datetime


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def handle_scan(scanner_key=None, data=None):
	if not scanner_key or not data:
		frappe.response["http_status_code"] = 400
		return _resp(success=False, error="scanner_key and data are required")

	scanner = _authenticate(scanner_key)
	if not scanner:
		frappe.response["http_status_code"] = 403
		return _resp(success=False, error="Invalid or inactive scanner key")

	# 1. Check if scanned data is a Workplace barcode
	workplace_name = frappe.db.get_value("Workplace", {"barcode": data}, "name")
	if workplace_name:
		frappe.db.set_value("Scanner Setup", scanner.name, "workplace", workplace_name)
		frappe.db.commit()
		emp = scanner.employee
		emp_label = frappe.db.get_value("Employee", emp, "employee_name") if emp else None
		return _resp(success=True, action="switch_workplace",
					message=f"Workplace: {workplace_name}",
					prompt=f"Workplace: {workplace_name} | Employee: {emp_label or '—'}",
					workplace=workplace_name, employee=emp)

	# 2. Check if scanned data is an Employee barcode (attendance_device_id)
	employee_name = frappe.db.get_value("Employee", {"attendance_device_id": data}, "name")
	if employee_name:
		frappe.db.set_value("Scanner Setup", scanner.name, "employee", employee_name)
		frappe.db.commit()
		emp_label = frappe.db.get_value("Employee", employee_name, "employee_name")
		wp = scanner.workplace or "—"
		return _resp(success=True, action="switch_employee",
					message=f"Employee: {emp_label or employee_name}",
					prompt=f"Workplace: {wp} | Employee: {emp_label or employee_name}",
					workplace=scanner.workplace, employee=employee_name)

	# 3. Need both workplace and employee
	if not scanner.workplace:
		frappe.db.commit()
		return _resp(success=False, error="No workplace assigned. Scan a workplace barcode first.")

	if not scanner.employee:
		frappe.db.commit()
		return _resp(success=False, error="No employee assigned. Scan an employee badge first.",
					workplace=scanner.workplace)

	workplace_doc = frappe.get_doc("Workplace", scanner.workplace)

	scripts = _get_scanner_scripts(scanner.workplace)
	if not scripts:
		frappe.db.commit()
		return _resp(success=False,
					error=f"No scanner scripts configured for workplace '{scanner.workplace}'")

	# Impersonate based on employee's user_id
	_impersonate(scanner.employee)

	scan_log = _create_scan_log(scanner, data)

	try:
		# 4. Resolve what was scanned
		scan_type, scan_ctx = _resolve_scan(data)

		# 5. Execute scripts (workplace-specific first, then general)
		result = None
		for script_doc in scripts:
			result = _execute_script(
				script_doc.script, scan_type, scan_ctx,
				data, scanner, workplace_doc, scanner.employee
			)
			if result:
				break

		if result:
			_update_scan_log(
				scan_log,
				status="Success",
				target_doctype=result.get("target_doctype"),
				target_document=result.get("target_document"),
				result_message=result.get("message"),
			)
			frappe.db.commit()
			return _resp(
				success=True,
				message=result.get("message"),
				prompt=result.get("prompt"),
				image=result.get("image"),
				workplace=scanner.workplace,
				employee=scanner.employee,
				scan_log=scan_log,
			)

		_update_scan_log(scan_log, status="Error",
						error_message=f"No handler for '{scan_type}' in scanner scripts")
		frappe.db.commit()
		return _resp(success=False,
					error=f"No handler for '{scan_type}' in scanner scripts",
					scan_log=scan_log)

	except Exception as e:
		_update_scan_log(scan_log, status="Error", error_message=str(e))
		frappe.db.commit()
		return _resp(success=False, error=str(e), scan_log=scan_log)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _authenticate(scanner_key):
	from erpnext.manufacturing.doctype.scanner_setup.scanner_setup import compute_auth_token

	for row in frappe.get_all("Scanner Setup", filters={"is_active": 1}, fields=["name", "api_key"]):
		if row.api_key and hmac.compare_digest(compute_auth_token(row.api_key), scanner_key):
			return frappe.get_doc("Scanner Setup", row.name)
	return None


def _get_scanner_scripts(workplace):
	workplace_scripts = frappe.get_all(
		"Scanner Script",
		filters={"is_active": 1, "workplace": workplace},
		fields=["name", "script"],
		order_by="creation",
	)
	general_scripts = frappe.get_all(
		"Scanner Script",
		filters={"is_active": 1, "workplace": ["is", "not set"]},
		fields=["name", "script"],
		order_by="creation",
	)
	return workplace_scripts + general_scripts


def _impersonate(employee_name):
	if employee_name:
		user_id = frappe.db.get_value("Employee", employee_name, "user_id")
		if user_id:
			frappe.set_user(user_id)
			return
	frappe.set_user("Administrator")


# ---------------------------------------------------------------------------
# Scan log
# ---------------------------------------------------------------------------

def _create_scan_log(scanner, data):
	log = frappe.new_doc("Scanner Scan Log")
	log.scanner = scanner.name
	log.timestamp = now_datetime()
	log.raw_data = data
	log.status = "Processing"
	log.flags.ignore_permissions = True
	log.insert()
	frappe.db.commit()
	return log.name


def _update_scan_log(log_name, **kwargs):
	updates = {}
	for key in ("status", "resolved_action", "scanner_mode", "target_doctype",
				"target_document", "result_message", "error_message"):
		if key in kwargs and kwargs[key] is not None:
			updates[key] = kwargs[key]
	if updates:
		frappe.db.set_value("Scanner Scan Log", log_name, updates)


# ---------------------------------------------------------------------------
# Resolution: what was scanned?
# ---------------------------------------------------------------------------

def _resolve_scan(data):
	if frappe.db.exists("Job Card", data):
		return "job_card", {"job_card": data, "doc": frappe.get_doc("Job Card", data)}

	if frappe.db.exists("Serial No", data):
		serial_doc = frappe.get_doc("Serial No", data)
		return "serial_no", {"serial_no": data, "item_code": serial_doc.item_code}

	item_barcode = frappe.db.get_value("Item Barcode", {"barcode": data}, "parent")
	if item_barcode:
		return "item", {"item_code": item_barcode, "barcode": data}

	if frappe.db.exists("Item", data):
		return "item", {"item_code": data, "barcode": None}

	return "unknown", {}


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------

def _execute_script(script, scan_type, scan_ctx, data, scanner, workplace_doc, employee):
	handler_name = f"on_{scan_type}_scanned"

	event = frappe._dict({
		"data": data,
		"scanner": scanner,
		"workplace": workplace_doc,
		"employee": employee,
		**scan_ctx,
	})

	script_globals = {
		"frappe": frappe,
		"json": json,
	}
	script_locals = {}

	exec(script, script_globals, script_locals)  # noqa: S102

	handler = script_locals.get(handler_name)
	if not handler:
		return None

	return handler(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(success=True, **kwargs):
	result = {"success": success}
	for key in ("action", "message", "error", "prompt", "mode",
				"scan_log", "target_doctype", "target_document",
				"workplace", "employee", "image"):
		if key in kwargs:
			result[key] = kwargs[key]
	return result
