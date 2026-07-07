import base64
import io
import json
import os
import socket
import tempfile
from urllib.parse import urlparse, urlunparse

import frappe


def detect_public_base_url() -> str:
	"""Return best-guess LAN-reachable server URL.

	Preference:
	1. Env var PUBLIC_SERVER_URL (explicit override).
	2. Incoming HTTP request Host header (what the user actually typed) — unless localhost.
	3. Socket-detected outbound LAN IP + scheme/port from get_url() — Docker bridge IPs
	   are filtered out (10.*, 172.16-31.*, 192.168.* accepted; but only if not the
	   container's own bridge subnet — best effort).
	4. frappe.utils.get_url() as-is.
	"""
	env = (os.environ.get("PUBLIC_SERVER_URL") or "").strip().rstrip("/")
	if env:
		return env

	base = frappe.utils.get_url() or "http://localhost:8080"
	parsed = urlparse(base)

	req_url = _url_from_request()
	if req_url:
		return req_url

	host = (parsed.hostname or "").lower()
	needs_swap = host in ("", "localhost", "127.0.0.1") or host.startswith("frontend") or host.startswith("backend")
	if not needs_swap:
		return base.rstrip("/")

	lan = _detect_lan_ip()
	if lan:
		port = f":{parsed.port}" if parsed.port else ""
		netloc = f"{lan}{port}"
		return urlunparse((parsed.scheme or "http", netloc, parsed.path or "", "", "", "")).rstrip("/")

	return base.rstrip("/")


def _url_from_request() -> str | None:
	try:
		req = getattr(frappe.local, "request", None)
		if req is None:
			return None
		host_hdr = (req.headers.get("X-Forwarded-Host") or req.headers.get("Host") or "").strip()
		if not host_hdr:
			return None
		hostname = host_hdr.split(":", 1)[0].lower()
		if hostname in ("localhost", "127.0.0.1", "") or hostname.startswith("frontend") or hostname.startswith("backend"):
			return None
		scheme = (req.headers.get("X-Forwarded-Proto") or req.scheme or "http").split(",")[0].strip()
		return f"{scheme}://{host_hdr}".rstrip("/")
	except Exception:
		return None


def _detect_lan_ip() -> str | None:
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.settimeout(0.5)
		s.connect(("8.8.8.8", 80))
		ip = s.getsockname()[0]
		s.close()
		if ip and not ip.startswith("127.") and ip != "0.0.0.0":
			return ip
	except Exception:
		return None
	return None

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

	if last:
		events.append({
			"index": g(last, "event_number", len(events) + 1),
			"distance_km": round(last_prop / 10000.0, 4),
			"event_code": evt_str(g(last, "event_code", "")),
			"slope_db_per_km": round((g(last, "attenuation_coefficient_lead_in_fiber", 0) or 0) / 1000.0, 4),
			"splice_loss_db": round((g(last, "event_loss", 0) or 0) / 1000.0, 4),
			"reflectance_db": round((g(last, "event_reflectance", 0) or 0) / 1000.0, 4),
			"loss_measurement_technique": g(last, "loss_measurement_technique", ""),
			"comment": g(last, "comment", ""),
			"is_end_of_fiber": True,
		})

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
		test_type="SOR",
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
		"sor": sor_info,
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
		test_type="SOR",
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
def submit_opm_measurement(
	otdr=None,
	wavelength_nm=None,
	power_dbm=None,
	power_mw=None,
	mode=None,
	reference=None,
	raw=None,
	**kwargs,
):
	"""Append a single Optical Power Meter reading to the OTDR's measurement log.

	Called by the Android app after paired OPM session. `test_type` is set to `OPM`
	so downstream reports/scripts can distinguish from SOR uploads.
	"""
	# Accept either query/form OTDR name or session-resolved OTDR
	if otdr:
		doc = frappe.get_doc("OTDR", otdr)
		doc.check_permission("write")
	else:
		doc = resolve_otdr_for_session()

	def _f(v):
		if v in (None, ""): return None
		try: return float(v)
		except (TypeError, ValueError): return None
	def _i(v):
		if v in (None, ""): return None
		try: return int(v)
		except (TypeError, ValueError): return None

	payload = {
		"test_type": "OPM",
		"wavelength_nm": _i(wavelength_nm),
		"power_dbm": _f(power_dbm),
		"power_mw": _f(power_mw),
		"mode": mode,
		"reference": _f(reference),
		"raw": raw,
	}
	payload_str = json.dumps(payload, ensure_ascii=False, default=str)
	result = doc.add_measurement_log(
		timestamp=frappe.utils.now_datetime(),
		test_type="OPM",
		status="Success",
		payload=payload_str,
		auto_sync=False,
	)
	# Fire Reflectometer scripts subscribed to 'OPM Measured'
	script_results = []
	try:
		from erpnext.manufacturing.doctype.device_script.device_script import run_scripts_for_event
		script_results = run_scripts_for_event(
			"Reflectometer", trigger_event="OPM Measured",
			otdr=doc, payload_str=payload_str,
		) or []
	except Exception:
		frappe.log_error(title="OPM script dispatch failed")
	return {"success": True, "row": (result or {}).get("row"), "script_results": script_results}


@frappe.whitelist(methods=["POST"])
def submit_vfl_event(otdr=None, duty=None, **kwargs):
	"""Log a Visual Fault Locator on/off event to the OTDR measurement log and
	fire any Reflectometer device scripts subscribed to 'VFL Toggled'.
	"""
	if otdr:
		doc = frappe.get_doc("OTDR", otdr)
		doc.check_permission("write")
	else:
		doc = resolve_otdr_for_session()

	try:
		duty_int = int(duty) if duty not in (None, "") else 0
	except (TypeError, ValueError):
		duty_int = 0

	payload = {"test_type": "VFL", "duty": duty_int, "state": "on" if duty_int > 0 else "off"}
	payload_str = json.dumps(payload, ensure_ascii=False, default=str)
	result = doc.add_measurement_log(
		timestamp=frappe.utils.now_datetime(),
		test_type="VFL",
		status="Success",
		payload=payload_str,
		auto_sync=False,
	)
	script_results = []
	try:
		from erpnext.manufacturing.doctype.device_script.device_script import run_scripts_for_event
		script_results = run_scripts_for_event(
			"Reflectometer", trigger_event="VFL Toggled",
			otdr=doc, payload_str=payload_str,
		) or []
	except Exception:
		frappe.log_error(title="VFL script dispatch failed")
	return {"success": True, "row": (result or {}).get("row"), "script_results": script_results}


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


@frappe.whitelist(methods=["GET", "POST"])
def get_default_connect_url(otdr_name):
	"""Return auto-detected LAN-reachable server URL for the Connect dialog."""
	doc = frappe.get_doc("OTDR", otdr_name)
	doc.check_permission("read")
	return {"server_url": detect_public_base_url(), "source": "auto"}


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

	server_url = (server_url or "").strip().rstrip("/") or detect_public_base_url()
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
