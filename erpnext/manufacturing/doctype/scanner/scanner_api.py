import hmac
import json
import time

import frappe
from frappe.utils import now_datetime


# ---------------------------------------------------------------------------
# State proxy — injected into script event as e.state
# ---------------------------------------------------------------------------

class ScannerStateProxy:
	def __init__(self, state_dict):
		self._current = state_dict or {}
		self._next = None
		self._cleared = False

	@property
	def name(self):
		return self._current.get("state")

	@property
	def context(self):
		return self._current.get("context", {})

	def set(self, state_name, context=None):
		self._next = {"state": state_name, "context": context or {}}

	def clear(self):
		self._cleared = True
		self._next = None


# ---------------------------------------------------------------------------
# Scan event — wraps frappe._dict with helper methods
# ---------------------------------------------------------------------------

class ScanEvent(frappe._dict):
	def set_workplace(self, workplace_name):
		frappe.db.set_value("Scanner", self.scanner.name, "workplace", workplace_name)
		self.scanner.workplace = workplace_name

	def set_employee(self, employee_name):
		frappe.db.set_value("Scanner", self.scanner.name, "employee", employee_name)
		self.scanner.employee = employee_name


# ---------------------------------------------------------------------------
# Redis state helpers
# ---------------------------------------------------------------------------

def _state_key(scanner_name):
	return f"scanner_state:{scanner_name}"


def _load_state(scanner_name, timeout):
	raw = frappe.cache().get_value(_state_key(scanner_name))
	if not raw:
		return None
	state = json.loads(raw)
	if time.time() - state.get("updated_at", 0) > timeout:
		_clear_state(scanner_name)
		return None
	return state


def _save_state(scanner_name, state_dict, timeout):
	state_dict["updated_at"] = time.time()
	frappe.cache().set_value(
		_state_key(scanner_name),
		json.dumps(state_dict),
		expires_in_sec=timeout,
	)


def _clear_state(scanner_name):
	frappe.cache().delete_value(_state_key(scanner_name))


def _persist_state(scanner_name, state_proxy, timeout):
	if state_proxy._cleared:
		_clear_state(scanner_name)
	elif state_proxy._next:
		_save_state(scanner_name, state_proxy._next, timeout)
	elif state_proxy.name:
		_save_state(scanner_name, state_proxy._current, timeout)


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def handle_scan(scanner_key=None, data=None):
	t_start = time.perf_counter()

	if not scanner_key or not data:
		frappe.response["http_status_code"] = 400
		return _resp(success=False, error="scanner_key and data are required")

	scanner = _authenticate(scanner_key)
	if not scanner:
		frappe.response["http_status_code"] = 403
		return _resp(success=False, error="Invalid or inactive scanner key")

	data = data.strip()

	state_timeout = scanner.get_state_timeout()
	state_dict = _load_state(scanner.name, state_timeout)
	state_proxy = ScannerStateProxy(state_dict)

	t_resolve_start = time.perf_counter()
	scan_type, scan_ctx = _resolve_scan(data)
	resolve_ms = int((time.perf_counter() - t_resolve_start) * 1000)

	workplace_doc = frappe.get_doc("Workplace", scanner.workplace) if scanner.workplace else None

	event = ScanEvent({
		"data": data,
		"scan_type": scan_type,
		"doc": scan_ctx.get("doc"),
		"item_code": scan_ctx.get("item_code"),
		"barcode": scan_ctx.get("barcode"),
		"scanner": scanner,
		"workplace": workplace_doc,
		"employee": scanner.employee,
		"state": state_proxy,
	})

	workplace_script = _get_workplace_script(scanner.workplace)
	if not workplace_script:
		frappe.db.commit()
		return _resp(success=False, error="No Workplace Script configured")

	_impersonate(scanner.employee)

	scan_log_row = _create_scan_log(scanner, data, state_proxy.name)

	try:
		scanner_scripts = frappe.get_all(
			"Scanner Script",
			filters={"is_active": 1},
			fields=["script_name", "script"],
		)

		t_script_start = time.perf_counter()
		result = _execute_workplace_script(workplace_script, event, scanner_scripts)
		script_ms = int((time.perf_counter() - t_script_start) * 1000)

		_persist_state(scanner.name, state_proxy, state_timeout)

		if result:
			message = result.get("message")
			if result.get("templateData") is not None:
				message = _apply_message_template(
					scanner, data, result.get("templateData")
				)

			total_ms = int((time.perf_counter() - t_start) * 1000)
			_update_scan_log(
				scanner,
				scan_log_row,
				status="Success",
				target_doctype=result.get("target_doctype"),
				target_document=result.get("target_document"),
				result_message=message,
				resolve_ms=resolve_ms,
				script_ms=script_ms,
				total_ms=total_ms,
			)
			frappe.db.commit()
			return _resp(
				success=True,
				message=message,
				prompt=result.get("prompt"),
				image=result.get("image"),
				workplace=scanner.workplace,
				employee=scanner.employee,
				state=state_proxy._next.get("state") if state_proxy._next else state_proxy.name if not state_proxy._cleared else None,
				scan_log=scan_log_row,
			)

		total_ms = int((time.perf_counter() - t_start) * 1000)
		_update_scan_log(scanner, scan_log_row, status="Error",
						error_message="on_scan handler not found or returned None",
						resolve_ms=resolve_ms, script_ms=script_ms, total_ms=total_ms)
		frappe.db.commit()
		return _resp(success=False,
					error="on_scan handler not found or returned None",
					scan_log=scan_log_row)

	except Exception as e:
		_persist_state(scanner.name, state_proxy, state_timeout)
		total_ms = int((time.perf_counter() - t_start) * 1000)
		_update_scan_log(scanner, scan_log_row, status="Error", error_message=str(e),
						resolve_ms=resolve_ms, total_ms=total_ms)
		frappe.db.commit()
		return _resp(success=False, error=str(e), scan_log=scan_log_row)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _authenticate(scanner_key):
	from erpnext.manufacturing.doctype.scanner.scanner import compute_auth_token

	for row in frappe.get_all("Scanner", filters={"is_active": 1}, fields=["name", "api_key"]):
		if row.api_key and hmac.compare_digest(compute_auth_token(row.api_key), scanner_key):
			return frappe.get_doc("Scanner", row.name)
	return None


def _get_workplace_script(workplace):
	script = None
	if workplace:
		script = frappe.db.get_value(
			"Workplace Script",
			{"is_active": 1, "workplace": workplace},
			["name", "script"],
			as_dict=True,
		)
	if not script:
		script = frappe.db.get_value(
			"Workplace Script",
			{"is_active": 1, "workplace": ["is", "not set"]},
			["name", "script"],
			as_dict=True,
		)
	return script


def _impersonate(employee_name):
	if employee_name:
		user_id = frappe.db.get_value("Employee", employee_name, "user_id")
		if user_id:
			frappe.set_user(user_id)
			return
	frappe.set_user("Administrator")


# ---------------------------------------------------------------------------
# Scan log (child table on Scanner doc)
# ---------------------------------------------------------------------------

def _create_scan_log(scanner, data, scanner_state=None):
	scanner.reload()
	row_name = scanner.add_scan_log(
		timestamp=now_datetime(),
		raw_data=data,
		status="Processing",
		scanner_state=scanner_state,
	)
	frappe.db.commit()
	return row_name


def _update_scan_log(scanner, row_name, **kwargs):
	updates = {}
	for key in ("status", "resolved_action", "scanner_mode", "scanner_state",
				"target_doctype", "target_document", "result_message", "error_message",
				"resolve_ms", "script_ms", "total_ms"):
		if key in kwargs and kwargs[key] is not None:
			updates[key] = kwargs[key]
	if updates:
		scanner.reload()
		scanner.update_scan_log(row_name, **updates)


# ---------------------------------------------------------------------------
# Resolution: what was scanned?
# ---------------------------------------------------------------------------

def _resolve_scan(data):
	wp = frappe.db.get_value("Workplace", {"barcode": data}, "name")
	if wp:
		return "workplace", {"doc": frappe.get_doc("Workplace", wp)}

	emp = frappe.db.get_value("Employee", {"attendance_device_id": data}, "name")
	if emp:
		return "employee", {"doc": frappe.get_doc("Employee", emp)}

	if frappe.db.exists("Job Card", data):
		return "job_card", {"doc": frappe.get_doc("Job Card", data)}

	if frappe.db.exists("Serial No", data):
		doc = frappe.get_doc("Serial No", data)
		return "serial_no", {"doc": doc, "item_code": doc.item_code}

	cmd = frappe.db.get_value("Scanner Command", {"barcode_id": data}, "name")
	if cmd:
		return "command", {"doc": frappe.get_doc("Scanner Command", cmd)}

	pkg_tmpl = frappe.db.get_value("Packing Template", {"barcode_id": data}, "name")
	if pkg_tmpl:
		return "packing_template", {"doc": frappe.get_doc("Packing Template", pkg_tmpl)}

	item_barcode = frappe.db.get_value("Item Barcode", {"barcode": data}, "parent")
	if item_barcode:
		return "item", {"doc": frappe.get_doc("Item", item_barcode), "item_code": item_barcode, "barcode": data}

	if frappe.db.exists("Item", data):
		return "item", {"doc": frappe.get_doc("Item", data), "item_code": data}

	return "unknown", {}


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------

def _execute_workplace_script(workplace_script, event, scanner_scripts):
	scripts = frappe._dict()
	for ss in scanner_scripts:
		ns = {"frappe": frappe, "json": json}
		exec(ss.script, ns)  # noqa: S102
		key = ss.script_name.lower().replace(" ", "_").replace("-", "_")
		scripts[key] = frappe._dict(ns)

	ws_ns = {"frappe": frappe, "json": json, "scripts": scripts}
	exec(workplace_script.script, ws_ns)  # noqa: S102

	handler = ws_ns.get("on_scan")
	if not handler:
		return None
	return handler(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_message_template(scanner, scanned_data, template_data):
	config = scanner.get_configuration()
	template = config.get("message_template") or ""
	if not template:
		return template_data or ""

	employee_name = ""
	if scanner.employee:
		employee_name = frappe.db.get_value("Employee", scanner.employee, "employee_name") or scanner.employee

	header = template.replace("{employee_name}", employee_name or "-")
	header = header.replace("{workplace}", scanner.workplace or "-")
	header = header.replace("{scanned_data}", scanned_data or "-")
	header = header.replace("\\n", "\n")

	if template_data:
		return header + template_data
	return header


def _resp(success=True, **kwargs):
	result = {"success": success}
	for key in ("action", "message", "error", "prompt", "mode",
				"scan_log", "target_doctype", "target_document",
				"workplace", "employee", "image", "state"):
		if key in kwargs:
			result[key] = kwargs[key]
	return result
