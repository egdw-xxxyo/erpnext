import json

import frappe
from frappe.model.document import Document


def _capture_working_copy(doc):
	return {"script": doc.script or ""}


def _load_snapshot(row):
	try:
		return json.loads(row.snapshot or "{}")
	except Exception:
		return {}


def _resolve_default_snapshot(doc):
	row = next((v for v in (doc.versions or []) if v.is_default), None)
	if not row:
		return _capture_working_copy(doc)
	return _load_snapshot(row)


class DeviceScript(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		default_version: DF.Data | None
		is_active: DF.Check
		script: DF.Code | None
		script_name: DF.Data | None
		script_type: DF.Literal["Scanner", "Reflectometer"]
		viewing_version: DF.Data | None

	def validate(self):
		if not self.script_type:
			self.script_type = "Scanner"

		if not self.versions:
			self.append("versions", {
				"version": "v1",
				"is_default": 1,
				"snapshot": json.dumps(_capture_working_copy(self)),
				"created_on": frappe.utils.now_datetime(),
			})
			self.default_version = "v1"
			self.viewing_version = "v1"

		defaults = [v for v in self.versions if v.is_default]
		if len(defaults) == 0:
			self.versions[0].is_default = 1
			defaults = [self.versions[0]]
		elif len(defaults) > 1:
			frappe.throw("Exactly one version must be marked as default")

		self.default_version = defaults[0].version

		if not self.viewing_version:
			self.viewing_version = self.default_version
		target = next((v for v in self.versions if v.version == self.viewing_version), None)
		if target is None:
			frappe.throw(f"Viewing version {self.viewing_version} not found")
		target.snapshot = json.dumps(_capture_working_copy(self))


def get_active_scripts(script_type: str = "Scanner", trigger_event: str | None = None):
	"""Return active Device Scripts of the given type with the script body from each default version snapshot."""
	filters = {"is_active": 1, "script_type": script_type}
	if trigger_event:
		filters["trigger_event"] = trigger_event
	names = frappe.get_all(
		"Device Script",
		filters=filters,
		pluck="name",
	)
	out = []
	for name in names:
		doc = frappe.get_cached_doc("Device Script", name)
		snap = _resolve_default_snapshot(doc)
		out.append(frappe._dict({
			"script_name": doc.script_name,
			"script_type": doc.script_type,
			"script": snap.get("script", "") or "",
		}))
	return out


def get_active_scanner_scripts():
	"""Backwards-compatible alias used by scanner_api during the transition."""
	return get_active_scripts("Scanner")


def run_scripts_for_event(script_type: str, trigger_event: str | None = None, **ctx_kwargs) -> list[dict]:
	"""Execute all active Device Scripts of `script_type` matching `trigger_event`. Errors are logged, not raised.

	Each script execution produces exactly one Device Script Run child row on the script.
	ctx.log(message, **extra) appends a line to the run's `logs` buffer.

	Returns list of per-script result dicts: {script, status, errors} where `errors` is a list of
	WARN/ERROR log lines captured during execution. Caller (e.g. submit_measurement) can surface
	these to the desktop app so the operator sees what went wrong.
	"""
	scripts = get_active_scripts(script_type, trigger_event=trigger_event)
	results: list[dict] = []
	if not scripts:
		return results
	if script_type == "Reflectometer":
		payload_str = ctx_kwargs.get("payload_str") or "{}"
		try:
			payload = json.loads(payload_str)
		except Exception:
			payload = {}
		otdr = ctx_kwargs.get("otdr")
		log_entry = ctx_kwargs.get("log_entry")
		ref_doctype = "OTDR" if otdr else None
		ref_name = getattr(otdr, "name", None) if otdr else None
		base_ctx_kwargs = dict(otdr=otdr, log_entry=log_entry, payload=payload)
		seed_context = {
			"otdr": ref_name,
			"log_entry": getattr(log_entry, "name", None),
			"payload_keys": list(payload.keys()) if isinstance(payload, dict) else None,
		}
	else:
		ref_doctype = ctx_kwargs.pop("_ref_doctype", None)
		ref_name = ctx_kwargs.pop("_ref_name", None)
		base_ctx_kwargs = dict(ctx_kwargs)
		seed_context = {}

	import time
	from erpnext.devices.doctype.device_script_run.device_script_run import insert_run

	fn_name = f"on_{script_type.lower()}"
	for s in scripts:
		ctx = frappe._dict(frappe=frappe, json=json, **base_ctx_kwargs)
		log_buf: list[str] = []

		def _log(message, level="INFO", _buf=log_buf, **extra):
			ts = frappe.utils.now_datetime().strftime("%H:%M:%S")
			line = f"[{ts}] {str(level).upper():5s} {message}"
			if extra:
				try:
					line += " " + json.dumps(extra, ensure_ascii=False, default=str)
				except Exception:
					line += f" {extra!r}"
			_buf.append(line)

		ctx.log = _log
		ns = {"frappe": frappe, "json": json, "ctx": ctx, "log": _log}
		t0 = time.perf_counter()
		status = "Success"
		try:
			exec(s.script, ns)  # noqa: S102
			fn = ns.get("on_event") or ns.get(fn_name)
			if callable(fn):
				fn(ctx)
		except Exception as e:
			status = "Error"
			log_buf.append(f"[ERROR] Script raised: {e}")
			log_buf.append(frappe.get_traceback())
			frappe.log_error(title=f"Device Script '{s.script_name}' failed")

		duration_ms = int((time.perf_counter() - t0) * 1000)
		insert_run(
			script_name=s.script_name,
			timestamp=frappe.utils.now_datetime(),
			status=status,
			duration_ms=duration_ms,
			logs="\n".join(log_buf) if log_buf else "(no log lines)",
			context=seed_context,
			reference_doctype=ref_doctype,
			reference_name=ref_name,
		)
		errors = [ln for ln in log_buf if " WARN " in ln or " ERROR " in ln or ln.startswith("[ERROR]")]
		results.append({
			"script": s.script_name,
			"status": status,
			"errors": errors,
		})
	return results
