import base64
import io
import json
import os
import tempfile

import frappe

from erpnext.manufacturing.doctype.otdr.otdr import push_status, resolve_otdr_for_session


def _parse_sor_file(path: str) -> dict:
	"""Parse SOR file via otdrs Rust wheel. Mirrors desktop read_sor_info."""
	import otdrs
	from datetime import datetime, timezone

	def g(o, k, d=None):
		try:
			v = getattr(o, k, d)
		except Exception:
			return d
		return v if v is not None else d

	def first(seq, d=0):
		try:
			return seq[0] if seq else d
		except Exception:
			return d

	def evt_str(t):
		if t is None:
			return ""
		try:
			b = bytes(t) if not isinstance(t, (bytes, bytearray, str)) else t
			if isinstance(b, (bytes, bytearray)):
				return b.decode("ascii", errors="replace").strip()
			return str(b).strip()
		except Exception:
			return str(t)

	sor = otdrs.parse_file(path)
	gp, fp, sp, ke = sor.general_parameters, sor.fixed_parameters, sor.supplier_parameters, sor.key_events

	ts = g(fp, "date_time_stamp", 0)
	try:
		dt_iso = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if ts else ""
	except Exception:
		dt_iso = str(ts)

	events = []
	for i, e in enumerate(g(ke, "key_events", []) or []):
		prop = g(e, "event_propogation_time", 0) or 0
		events.append({
			"index": g(e, "event_number", i + 1),
			"distance_km": round(prop / 10000.0, 4),
			"event_code": evt_str(g(e, "event_code", "")),
			"slope_db_per_km": round((g(e, "attenuation_coefficient_lead_in_fiber", 0) or 0) / 1000.0, 4),
			"splice_loss_db": round((g(e, "event_loss", 0) or 0) / 1000.0, 4),
			"reflectance_db": round((g(e, "event_reflectance", 0) or 0) / 1000.0, 4),
			"loss_measurement_technique": g(e, "loss_measurement_technique", ""),
			"comment": g(e, "comment", ""),
		})

	last = g(ke, "last_key_event", None)
	end_to_end_db = round((g(last, "end_to_end_loss", 0) or 0) / 1000.0, 4) if last else None
	orl_db = round((g(last, "optical_return_loss", 0) or 0) / 1000.0, 4) if last else None
	last_prop = (g(last, "event_propogation_time", 0) or 0) if last else 0
	fiber_length_km = round(last_prop / 10000.0, 4) if last else None

	return {
		"Acquisition": {
			"wavelength_nm": round((g(fp, "actual_wavelength", 0) or 0) / 10.0, 1),
			"pulse_width_ns": first(g(fp, "pulse_widths_used", []) or [], 0),
			"range_km": round((g(fp, "acquisition_range", 0) or 0) / 1000.0, 4),
			"averages": g(fp, "number_of_averages", 0),
			"averaging_time_s": g(fp, "averaging_time", 0),
			"date_time_utc": dt_iso,
			"units": g(fp, "units_of_distance", ""),
			"trace_type": g(fp, "trace_type", ""),
		},
		"Fiber": {
			"group_index": round((g(fp, "group_index", 0) or 0) / 100000.0, 5),
			"backscatter_db": -round((g(fp, "backscatter_coefficient", 0) or 0) / 10.0, 1),
			"loss_threshold_db": round((g(fp, "loss_threshold", 0) or 0) / 1000.0, 3),
			"reflectance_threshold_db": -round((g(fp, "reflectance_threshold", 0) or 0) / 1000.0, 3),
			"end_of_fibre_threshold_db": round((g(fp, "end_of_fibre_threshold", 0) or 0) / 1000.0, 3),
		},
		"General": {
			"fiber_id": g(gp, "fiber_id", ""),
			"cable_id": g(gp, "cable_id", ""),
			"operator": g(gp, "operator", ""),
			"comment": g(gp, "comment", ""),
			"originating_location": g(gp, "originating_location", ""),
			"terminating_location": g(gp, "terminating_location", ""),
			"nominal_wavelength_nm": g(gp, "nominal_wavelength", 0),
			"fiber_type": g(gp, "fiber_type", 0),
		},
		"Supplier": {
			"supplier_name": g(sp, "supplier_name", ""),
			"mainframe_id": g(sp, "otdr_mainframe_id", ""),
			"mainframe_sn": g(sp, "otdr_mainframe_sn", ""),
			"module_id": g(sp, "optical_module_id", ""),
			"module_sn": g(sp, "optical_module_sn", ""),
			"software_revision": g(sp, "software_revision", ""),
		},
		"Events": events,
		"Summary": {
			"n_events": g(ke, "number_of_key_events", len(events)),
			"fiber_length_km": fiber_length_km,
			"end_to_end_loss_db": end_to_end_db,
			"optical_return_loss_db": orl_db,
		},
	}


@frappe.whitelist(methods=["POST"])
def parse_and_submit_measurement(auto_sync=None, remote_path=None, filename=None, **kwargs):
	"""Accept raw SOR file bytes (multipart 'file'), parse server-side, submit as measurement.

	Single source of truth for SOR parsing — both desktop + Android clients call this.
	"""
	otdr = resolve_otdr_for_session()
	files = frappe.request.files if frappe.request is not None else None
	f = files.get("file") if files else None
	if f is None:
		frappe.throw("Missing 'file' multipart field")

	auto_sync_flag = str(auto_sync or "").lower() in ("1", "true", "yes")
	fname = filename or getattr(f, "filename", None) or "upload.sor"

	raw = f.read()
	size = len(raw)

	tmp = tempfile.NamedTemporaryFile(prefix="sor_", suffix=".sor", delete=False)
	tmp.write(raw)
	tmp.close()
	parsed_ok = True
	error = None
	sor_info = None
	try:
		sor_info = _parse_sor_file(tmp.name)
	except Exception as e:
		parsed_ok = False
		error = f"parse failed: {e}"
	finally:
		try:
			os.unlink(tmp.name)
		except Exception:
			pass

	payload = {
		"filename": fname,
		"remote_path": remote_path or "",
		"size_bytes": size,
	}
	if sor_info:
		payload["sor"] = sor_info
		summary = sor_info.get("Summary") or {}
		acq = sor_info.get("Acquisition") or {}
		if "end_to_end_loss_db" in summary:
			payload["loss_db"] = summary["end_to_end_loss_db"]
		if "fiber_length_km" in summary:
			payload["distance_km"] = summary["fiber_length_km"]
		if "wavelength_nm" in acq:
			payload["wavelength_nm"] = acq["wavelength_nm"]

	payload_str = json.dumps(payload, ensure_ascii=False, default=str)
	result = otdr.add_measurement_log(
		timestamp=frappe.utils.now_datetime(),
		status="Success" if parsed_ok else "Error",
		payload=payload_str,
		error_message=error,
		auto_sync=auto_sync_flag,
	)
	script_results = (result or {}).get("script_results", []) if isinstance(result, dict) else []
	return {
		"success": parsed_ok,
		"error": error,
		"auto_sync": auto_sync_flag,
		"script_results": script_results,
	}


@frappe.whitelist(methods=["POST"])
def submit_measurement(data=None, auto_sync=None, **kwargs):
	otdr = resolve_otdr_for_session()

	qs_auto = ""
	if frappe.request is not None:
		try:
			qs_auto = frappe.request.args.get("auto_sync", "") or ""
		except Exception:
			qs_auto = ""
	auto_sync_flag = str(auto_sync or qs_auto or frappe.local.form_dict.get("auto_sync") or "").lower() in ("1", "true", "yes")

	if data is None:
		body_dict = {k: v for k, v in (frappe.local.form_dict or {}).items() if k not in ("cmd", "auto_sync")}
		if body_dict:
			data = body_dict
		elif frappe.request is not None:
			raw = frappe.request.get_data(as_text=True)
			data = raw or None

	parsed_ok = True
	error = None
	if isinstance(data, (dict, list)):
		payload_str = json.dumps(data, ensure_ascii=False, default=str)
	elif data:
		payload_str = data
		try:
			json.loads(payload_str)
		except Exception as e:
			parsed_ok = False
			error = str(e)
	else:
		payload_str = ""
		parsed_ok = False
		error = "empty body"

	result = otdr.add_measurement_log(
		timestamp=frappe.utils.now_datetime(),
		status="Success" if parsed_ok else "Error",
		payload=payload_str,
		error_message=error,
		auto_sync=auto_sync_flag,
	)

	script_results = (result or {}).get("script_results", []) if isinstance(result, dict) else []
	return {
		"success": parsed_ok,
		"error": error,
		"auto_sync": auto_sync_flag,
		"script_results": script_results,
	}


@frappe.whitelist(methods=["POST"])
def update_status(status=None, file=None, progress=None, total=None, **kwargs):
	otdr = resolve_otdr_for_session()

	def _int(v):
		if v in (None, ""):
			return None
		try:
			return int(v)
		except (TypeError, ValueError):
			return None

	extra = {k: v for k, v in kwargs.items() if k not in ("cmd",) and not k.startswith("_")}
	push_status(
		otdr.name,
		status=status,
		file=file,
		progress=_int(progress),
		total=_int(total),
		**extra,
	)

	return {"success": True}


@frappe.whitelist(methods=["GET"])
def get_configuration(**kwargs):
	otdr = resolve_otdr_for_session()
	return otdr.get_configuration_payload()


@frappe.whitelist(methods=["GET"])
def who_am_i(**kwargs):
	"""Debug: returns the OTDR resolved for current session user."""
	otdr = resolve_otdr_for_session()
	return {"otdr": otdr.name, "user": frappe.session.user}


@frappe.whitelist(methods=["GET"])
def get_default_connect_url(otdr_name):
	"""Return the URL to prefill in the Connect Reflectometer dialog.

	Preference order:
	1. OTDR Configuration → public_server_url (admin-set LAN/public URL)
	2. frappe.utils.get_url() (may be internal in Docker)
	"""
	doc = frappe.get_doc("OTDR", otdr_name)
	doc.check_permission("read")
	cfg_url = None
	if doc.otdr_configuration:
		cfg_url = frappe.db.get_value("OTDR Configuration", doc.otdr_configuration, "public_server_url")
	url = (cfg_url or "").strip().rstrip("/") or frappe.utils.get_url()
	return {"server_url": url, "source": "configuration" if cfg_url else "site"}


@frappe.whitelist(methods=["POST"])
def generate_connect_bundle(otdr_name, server_url=None):
	"""Regenerate api_key/api_secret for the OTDR's device_user and return a full
	connect bundle (server URL, keys, base64 config token, QR data URI).

	server_url is the client-visible URL (from browser). Fallback to frappe.utils.get_url()
	which may return an internal hostname on Dockerized setups.

	Secret is only returned once at generation time — the caller UI must warn
	the user to copy it now.
	"""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("OTDR", otdr_name)
	doc.check_permission("write")
	if not doc.device_user:
		frappe.throw("OTDR has no device_user assigned")

	from frappe.core.doctype.user.user import generate_keys
	keys = generate_keys(doc.device_user)
	api_key = keys.get("api_key")
	api_secret = keys.get("api_secret")

	server_url = (server_url or "").strip().rstrip("/") or frappe.utils.get_url()
	config = {
		"v": 1,
		"server_url": server_url,
		"api_key": api_key,
		"api_secret": api_secret,
		"otdr": doc.name,
	}
	token = base64.urlsafe_b64encode(
		json.dumps(config, separators=(",", ":")).encode("utf-8")
	).decode("ascii")

	qr_data_uri = _make_qr_data_uri(token)

	return {
		"server_url": server_url,
		"api_key": api_key,
		"api_secret": api_secret,
		"device_user": doc.device_user,
		"token": token,
		"qr_data_uri": qr_data_uri,
	}


def _make_qr_data_uri(text: str) -> str:
	import qrcode
	from qrcode.constants import ERROR_CORRECT_M

	qr = qrcode.QRCode(
		version=None,
		error_correction=ERROR_CORRECT_M,
		box_size=6,
		border=2,
	)
	qr.add_data(text)
	qr.make(fit=True)
	img = qr.make_image(fill_color="black", back_color="white")
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
