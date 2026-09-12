"""Run a workplace's Workplace Script for something that is not a barcode scan.

The state machine was built for scanners: `scanner_api.handle_scan` authenticates a
`Scanner` record by HMAC, impersonates that scanner's employee, and keys Redis state by
scanner name. A reflectometer measurement arrives instead from a phone with a logged-in
session and no Scanner record at all, so it needs its own way in.

What is shared with the scanner path, by import rather than by copy:
`ScannerStateProxy` (the Redis-backed state object), `_get_workplace_script` (per-workplace
script with a site-wide fallback), `_build_scripts_namespace` (Scanner-type Device Scripts
exec'd into the `scripts.*` library namespace) and `ScriptLogger`.

What is deliberately NOT shared:

* **The Redis key.** Scanner state stays under `scanner_state:{scanner}`; measurements use
  `otdr_state:{workplace}:{user}`. Keying by workplace alone would make two operators at one
  bench overwrite each other's state mid-flow.
* **The event class.** `ScanEvent.set_workplace` / `set_employee` write to a `Scanner`
  document, which does not exist here, so `MeasurementEvent` is a sibling rather than a
  subclass.
* **The handler name.** State scripts implement `on_measurement(e)`, so one workplace can
  answer both a scan and a trace without the two handlers colliding.
"""

import json
import time

import frappe

from erpnext.devices.doctype.scanner.scanner_api import (
	ScannerStateProxy,
	ScriptLogger,
	_build_scripts_namespace,
	_get_workplace_script,
)

DEFAULT_STATE_TIMEOUT = 300


class MeasurementEvent(frappe._dict):
	"""What a state script receives as `e` for a measurement.

	`scanner` is present and None on purpose: shared library scripts under `scripts.*` were
	written against scan events and commonly probe `e.scanner`, which should read as "no
	scanner" rather than raise.
	"""

	def set_state(self, state_name, context=None):
		self.state.set(state_name, context)


def _state_key(workplace, user):
	return f"otdr_state:{workplace}:{user}"


def _load_state(workplace, user, timeout):
	raw = frappe.cache().get_value(_state_key(workplace, user))
	if not raw:
		return None
	try:
		state = json.loads(raw)
	except Exception:
		return None
	if time.time() - state.get("updated_at", 0) > timeout:
		_clear_state(workplace, user)
		return None
	return state


def _save_state(workplace, user, state_dict, timeout):
	state_dict["updated_at"] = time.time()
	frappe.cache().set_value(
		_state_key(workplace, user),
		json.dumps(state_dict),
		expires_in_sec=timeout,
	)


def _clear_state(workplace, user):
	frappe.cache().delete_value(_state_key(workplace, user))


def _persist_state(workplace, user, state_proxy, timeout):
	if state_proxy._cleared:
		_clear_state(workplace, user)
		return
	if state_proxy._next:
		_save_state(workplace, user, state_proxy._next, timeout)
	elif state_proxy.name:
		_save_state(workplace, user, state_proxy._current, timeout)


def _scanner_scripts():
	"""Scanner-type Device Scripts, exec'd into the `scripts.*` library namespace.

	Same library set the scanner benches get — a helper written for a scan is just as useful
	to a measurement, and keeping one namespace avoids a second place to register helpers.
	"""
	from erpnext.devices.doctype.device_script.device_script import get_active_scripts

	return _build_scripts_namespace(get_active_scripts("Scanner"))


def dispatch_measurement(workplace, employee=None, **event_fields):
	"""Run the workplace's script for one measurement.

	Returns `(result, info)` where `result` is whatever the state script returned (or None)
	and `info` carries the state name and the captured log lines, which the caller stamps
	onto the OTDR Measurement record so a bad run is diagnosable after the fact.

	Exceptions are caught, not raised: a script error must still leave a measurement record
	and a readable message on the operator's phone.
	"""
	user = frappe.session.user
	timeout = DEFAULT_STATE_TIMEOUT

	state_proxy = ScannerStateProxy(_load_state(workplace, user, timeout))
	logger = ScriptLogger()

	workplace_doc = frappe.get_cached_doc("Workplace", workplace) if workplace else None

	event = MeasurementEvent(
		{
			"scan_type": "otdr_measurement",
			"scanner": None,
			"workplace": workplace_doc,
			"employee": employee,
			"state": state_proxy,
			"logger": logger,
			**event_fields,
		}
	)

	script = _get_workplace_script(workplace)
	if not script:
		logger.error("No Workplace Script configured for this workplace")
		return None, {"state": state_proxy.name, "logs": logger.render(), "error": "no_script"}

	result = None
	error = None
	try:
		from erpnext.devices.doctype.workplace_script.workplace_script import (
			_resolve_default_snapshot,
		)

		doc = frappe.get_cached_doc("Workplace Script", script.name)
		snap = _resolve_default_snapshot(doc)
		ns = {"frappe": frappe, "json": json, "scripts": _scanner_scripts()}
		exec(snap.get("script", "") or "", ns)

		handler = ns.get("on_measurement")
		if handler:
			result = handler(event)
		else:
			logger.error(f"Workplace Script '{script.name}' defines no on_measurement(e)")
			error = "no_handler"
	except Exception as e:
		error = str(e)
		logger.error(f"Script raised: {e}")
		frappe.log_error(title=f"Workplace Script '{script.name}' failed on measurement")
	finally:
		_persist_state(workplace, user, state_proxy, timeout)

	final_state = (
		state_proxy._next.get("state")
		if state_proxy._next
		else (state_proxy.name if not state_proxy._cleared else None)
	)
	return result, {
		"state": final_state,
		"logs": logger.render(),
		"script": script.name,
		"error": error,
	}
