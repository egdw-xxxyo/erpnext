import json
import re
import socket

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class LabelPrinter(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link | None
		description: DF.SmallText | None
		ip_address: DF.Data | None
		is_enabled: DF.Check
		is_label_change_in_progress: DF.Check
		label_change_message: DF.Data | None
		last_checked: DF.Datetime | None
		last_status: DF.Data | None
		loaded_label_size: DF.Link | None
		port: DF.Int
		printer_info: DF.Code | None
		printer_model: DF.Literal["Godex G530", "Godex G500", "Godex G300", "Other"]
		printer_name: DF.Data | None
		timeout: DF.Int
		web_password: DF.Password | None
		web_username: DF.Data | None

	def validate(self):
		self._validate_ip()
		self._validate_port()

	def _validate_ip(self):
		if not self.ip_address:
			return
		pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
		if not re.match(pattern, self.ip_address):
			frappe.throw(_("Invalid IP address format"))
		for octet in self.ip_address.split("."):
			if int(octet) > 255:
				frappe.throw(_("Invalid IP address format"))

	def _validate_port(self):
		if self.port and (self.port < 1 or self.port > 65535):
			frappe.throw(_("Port must be between 1 and 65535"))


# ---------------------------------------------------------------------------
# Low-level TCP helpers
# ---------------------------------------------------------------------------

def _tcp_query(ip, port, command, timeout=5, recv_timeout=0.5):
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	sock.settimeout(timeout)
	try:
		sock.connect((ip, port))
		sock.sendall(f"{command}\r\n".encode())
		sock.settimeout(recv_timeout)
		response = b""
		try:
			while True:
				chunk = sock.recv(4096)
				if not chunk:
					break
				response += chunk
		except socket.timeout:
			pass
		return response.decode("utf-8", errors="replace").strip()
	finally:
		sock.close()


def _tcp_send_raw(ip, port, data, timeout=5):
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	sock.settimeout(timeout)
	try:
		sock.connect((ip, port))
		sock.sendall(data)
	finally:
		sock.close()


def _send_ezpl(printer_doc, ezpl_str):
	payload = ezpl_str.encode("cp1251", errors="replace")
	frappe.logger("label_printer").info(
		f"_send_ezpl: sending {len(payload)} bytes to {printer_doc.ip_address}:{printer_doc.port}"
	)
	_tcp_send_raw(printer_doc.ip_address, printer_doc.port, payload, printer_doc.timeout or 5)
	frappe.logger("label_printer").info("_send_ezpl: sent successfully")


# ---------------------------------------------------------------------------
# EZPL label builder
# ---------------------------------------------------------------------------

def build_ezpl_label(content_lines, width_mm=65, height_mm=20, gap_mm=3, heat=13, copies=1):
	lines = []
	lines.append(f"^Q{height_mm},{gap_mm}")
	lines.append(f"^W{width_mm}")
	lines.append(f"^E{heat}")
	lines.append("^L")
	lines.extend(content_lines)
	lines.append("E")
	return "\r\n".join(lines) + "\r\n"


def build_text_line(x, y, text, font="A", h_mult=2, v_mult=2):
	return f"A{font},{x},{y},{h_mult},{v_mult},0,0,{text}"


def build_barcode_128(x, y, text, narrow=2, wide=6, height=80):
	return f"BA,{x},{y},{narrow},{wide},{height},0,0,{text}"


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def _get_printer_doc(printer_name):
	doc = frappe.get_doc("Label Printer", printer_name)
	if not doc.is_enabled:
		frappe.throw(_("Printer {0} is disabled").format(printer_name))
	return doc


def _mm_to_dots(mm, dpi):
	return int(float(mm) * dpi / 25.4)


def _parse_host_status(raw):
	lines = [l.strip() for l in raw.split("\n") if l.strip()]
	result = {}
	for line in lines:
		clean = line.strip("\x02\x03\r")
		if not clean:
			continue
		parts = clean.split(",")
		if len(parts) >= 12 and "paper_out" not in result:
			result["paper_out"] = int(parts[1]) if parts[1].isdigit() else 0
			result["pause"] = int(parts[2]) if parts[2].isdigit() else 0
			result["label_length"] = parts[3].strip() if len(parts) > 3 else ""
			result["head_up"] = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
			result["ribbon_out"] = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0
		elif len(parts) >= 8 and "function_settings" not in result:
			result["function_settings"] = clean
	if not any(result.get(k) for k in ["paper_out", "head_up", "ribbon_out"]):
		result["status"] = "Ready"
	else:
		errors = []
		if result.get("paper_out"):
			errors.append("Paper Out")
		if result.get("head_up"):
			errors.append("Head Open")
		if result.get("ribbon_out"):
			errors.append("Ribbon Out")
		result["status"] = "Error: " + ", ".join(errors)
	return result


def _parse_host_info(raw):
	clean = raw.strip("\x02\x03\r\n")
	parts = [p.strip() for p in clean.split(",")]
	result = {}
	if len(parts) >= 1:
		result["model"] = parts[0]
	if len(parts) >= 2:
		result["firmware"] = parts[1]
	if len(parts) >= 3:
		result["dpi_code"] = parts[2]
	if len(parts) >= 4:
		result["memory"] = parts[3]
	return result


def _parse_head_diagnostic(raw):
	result = {}
	for line in raw.split("\n"):
		line = line.strip("\r\x02\x03 ")
		if "=" in line:
			key, _, val = line.partition("=")
			key = key.strip().lower().replace(" ", "_")
			result[key] = val.strip()
	return result


def _parse_memory_info(raw):
	clean = raw.strip("\x02\x03\r\n")
	parts = [p.strip() for p in clean.split(",")]
	result = {}
	if len(parts) >= 1:
		result["total_kb"] = parts[0]
	if len(parts) >= 2:
		result["ram_available_kb"] = parts[1]
	if len(parts) >= 3:
		result["flash_available_kb"] = parts[2]
	return result


# ---------------------------------------------------------------------------
# Whitelisted API — status / info
# ---------------------------------------------------------------------------

@frappe.whitelist()
def check_connection(printer_name):
	doc = frappe.get_doc("Label Printer", printer_name)
	timeout = min(doc.timeout or 5, 3)
	try:
		raw_info = _tcp_query(doc.ip_address, doc.port, "~HI", timeout)
		info = _parse_host_info(raw_info)
		frappe.db.set_value("Label Printer", printer_name, {
			"last_status": "Ready",
			"last_checked": now_datetime(),
		}, update_modified=False)
		return {"connected": True, "status": "Ready", "identification": info}
	except socket.error as e:
		frappe.db.set_value("Label Printer", printer_name, {
			"last_status": f"Connection Error",
			"last_checked": now_datetime(),
		}, update_modified=False)
		return {"connected": False, "status": str(e)}


@frappe.whitelist()
def check_status(printer_name):
	doc = _get_printer_doc(printer_name)
	try:
		raw_status = _tcp_query(doc.ip_address, doc.port, "~HS", doc.timeout or 5)
		raw_info = _tcp_query(doc.ip_address, doc.port, "~HI", doc.timeout or 5)

		status = _parse_host_status(raw_status)
		info = _parse_host_info(raw_info)

		combined = {"status": status, "identification": info}

		frappe.db.set_value("Label Printer", printer_name, {
			"last_status": status.get("status", "Unknown"),
			"last_checked": now_datetime(),
			"printer_info": json.dumps(combined, indent=2, ensure_ascii=False),
		})

		return combined
	except socket.error as e:
		frappe.db.set_value("Label Printer", printer_name, {
			"last_status": f"Connection Error: {e}",
			"last_checked": now_datetime(),
		})
		frappe.throw(_("Cannot connect to printer: {0}").format(str(e)))


def _refresh_printer_info(printer_name):
	doc = _get_printer_doc(printer_name)
	timeout = doc.timeout or 5

	raw_hi = _tcp_query(doc.ip_address, doc.port, "~HI", timeout)
	raw_hd = _tcp_query(doc.ip_address, doc.port, "~HD", timeout)
	raw_hm = _tcp_query(doc.ip_address, doc.port, "~HM", timeout)
	raw_hs = _tcp_query(doc.ip_address, doc.port, "~HS", timeout)

	result = {
		"identification": _parse_host_info(raw_hi),
		"diagnostics": _parse_head_diagnostic(raw_hd),
		"memory": _parse_memory_info(raw_hm),
		"status": _parse_host_status(raw_hs),
	}

	update = {
		"last_status": result["status"].get("status", "Unknown"),
		"last_checked": now_datetime(),
		"printer_info": json.dumps(result, indent=2, ensure_ascii=False),
	}
	dpi_code = result.get("identification", {}).get("dpi_code")
	if dpi_code:
		try:
			update["dpi"] = int(round(int(dpi_code) * 25.4))
		except (ValueError, TypeError):
			pass
	frappe.db.set_value("Label Printer", printer_name, update)

	return result


@frappe.whitelist()
def get_printer_info(printer_name):
	try:
		return _refresh_printer_info(printer_name)
	except socket.error as e:
		frappe.throw(_("Cannot connect to printer: {0}").format(str(e)))


@frappe.whitelist()
def send_raw_command(printer_name, command):
	doc = _get_printer_doc(printer_name)
	try:
		response = _tcp_query(doc.ip_address, doc.port, command, doc.timeout or 5)
		return {"command": command, "response": response}
	except socket.error as e:
		frappe.throw(_("Cannot connect to printer: {0}").format(str(e)))


@frappe.whitelist()
def beep(printer_name):
	doc = _get_printer_doc(printer_name)
	try:
		_tcp_send_raw(
			doc.ip_address, doc.port,
			b"^XSET,BUZZ,200\r\n",
			doc.timeout or 5,
		)
		return {"success": True}
	except socket.error as e:
		frappe.throw(_("Cannot connect to printer: {0}").format(str(e)))


# ---------------------------------------------------------------------------
# Whitelisted API — printing
# ---------------------------------------------------------------------------

@frappe.whitelist()
def print_test_label(printer_name, text, text2=None):
	printer = _get_printer_doc(printer_name)

	width_mm = 65
	height_mm = 20
	gap_mm = 3
	if printer.loaded_label_size:
		size = frappe.get_doc("Label Size", printer.loaded_label_size)
		width_mm = int(size.width_mm)
		height_mm = int(size.height_mm)

	content = [build_text_line(50, 20, text, font="A", h_mult=3, v_mult=3)]
	if text2:
		content.append(build_text_line(50, 100, text2, font="A", h_mult=2, v_mult=2))

	ezpl = build_ezpl_label(content, width_mm=width_mm, height_mm=height_mm, gap_mm=gap_mm)
	_send_ezpl(printer, ezpl)
	return {"success": True, "ezpl": ezpl}


@frappe.whitelist()
def print_calibration_label(printer_name):
	printer = _get_printer_doc(printer_name)

	if not printer.loaded_label_size:
		frappe.throw(_("Set a Loaded Label Size on the printer first"))

	size = frappe.get_doc("Label Size", printer.loaded_label_size)
	dpi = int(printer.dpi or 300)
	w_mm = int(size.width_mm)
	h_mm = int(size.height_mm)
	w_px = _mm_to_dots(size.width_mm, dpi)
	h_px = _mm_to_dots(size.height_mm, dpi)

	ox = int(getattr(printer, "offset_x", 0) or 0)
	oy = int(getattr(printer, "offset_y", 0) or 0)

	html = f"""<!DOCTYPE html>
<html><head><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{w_px}px; height:{h_px}px; position:relative; font-family:monospace; }}
.border {{ position:absolute; top:2px; left:2px; right:2px; bottom:2px; border:3px solid #000; }}
.cross-h {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); width:60px; height:3px; background:#000; }}
.cross-v {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); width:3px; height:60px; background:#000; }}
.corner {{ position:absolute; width:24px; height:24px; }}
.corner::before {{ content:''; position:absolute; top:50%; left:0; right:0; height:3px; background:#000; transform:translateY(-50%); }}
.corner::after {{ content:''; position:absolute; left:50%; top:0; bottom:0; width:3px; background:#000; transform:translateX(-50%); }}
.tl {{ top:12px; left:12px; }}
.tr {{ top:12px; right:12px; }}
.bl {{ bottom:12px; left:12px; }}
.br {{ bottom:12px; right:12px; }}
.info {{ position:absolute; top:20px; left:40px; font-size:18px; font-weight:bold; }}
.hint {{ position:absolute; bottom:16px; left:40px; font-size:14px; }}
</style></head><body>
<div class="border"></div>
<div class="cross-h"></div>
<div class="cross-v"></div>
<div class="corner tl"></div>
<div class="corner tr"></div>
<div class="corner bl"></div>
<div class="corner br"></div>
<div class="info">{w_mm}x{h_mm}mm | offset X={ox} Y={oy}</div>
<div class="hint">Adjust offset until border is even on all sides</div>
</body></html>"""

	pcx_data, png_data = _html_to_image(html, w_px, h_px)
	_send_pcx_label(printer, pcx_data, size)
	return {"success": True, "width_mm": w_mm, "height_mm": h_mm, "offset_x": ox, "offset_y": oy}


@frappe.whitelist()
def test_print(printer_name, template_name):
	printer = _get_printer_doc(printer_name)
	template = frappe.get_doc("Label Template", template_name)

	data = None
	if template.preview_data:
		data = json.loads(template.preview_data)

	ezpl = _render_template(template, data=data)
	_send_ezpl(printer, ezpl)
	return {"success": True}


@frappe.whitelist()
def print_label(print_job_name):
	job = frappe.get_doc("Print Job", print_job_name)
	frappe.logger("label_printer").info(
		f"print_label called: job={print_job_name}, status={job.status}, "
		f"template={job.label_template}, printer={job.label_printer}"
	)

	if job.status not in ("Queued", "Failed", "Printed"):
		frappe.throw(_("Print Job {0} is not in a printable state (status: {1})").format(
			print_job_name, job.status
		))

	printer = _get_printer_doc(job.label_printer)

	if printer.is_label_change_in_progress:
		frappe.throw(_("Printer {0} is changing labels. Please wait.").format(job.label_printer))

	if job.label_size and printer.loaded_label_size and job.label_size != printer.loaded_label_size:
		frappe.throw(
			_("Label size mismatch: job requires {0} but printer has {1} loaded").format(
				job.label_size, printer.loaded_label_size
			)
		)

	template = frappe.get_doc("Label Template", job.label_template)
	frappe.logger("label_printer").info(
		f"Template loaded: type={template.template_type}, "
		f"has_ezpl={bool(template.zpl_template)}, size={template.label_size}"
	)

	ref_doc = None
	raw_data = None
	if job.reference_doctype and job.reference_name:
		ref_doc = frappe.get_doc(job.reference_doctype, job.reference_name)
		frappe.logger("label_printer").info(f"Reference doc: {job.reference_doctype}/{job.reference_name}")
	elif not job.reference_doctype:
		if job.raw_data:
			raw_data = json.loads(job.raw_data)
		elif job.reference_name:
			raw_data = {"name": job.reference_name}
		frappe.logger("label_printer").info(f"Raw data: {raw_data}")

	parent_doc = None
	if job.parent_doctype and job.parent_name:
		parent_doc = frappe.get_doc(job.parent_doctype, job.parent_name)
		frappe.logger("label_printer").info(f"Parent doc: {job.parent_doctype}/{job.parent_name}")

	try:
		frappe.db.set_value("Print Job", print_job_name, "status", "Printing")

		if template.template_type == "HTML":
			rendered_html = _render_html_template(template, doc=ref_doc, data=raw_data, parent_doc=parent_doc)
			frappe.logger("label_printer").info(
				f"Rendered HTML ({len(rendered_html)} chars)"
			)
			if not rendered_html or not rendered_html.strip():
				raise ValueError("Template rendered empty HTML output")

			size = frappe.get_doc("Label Size", template.label_size)
			dpi = int(printer.dpi or 300)
			w_dots = _mm_to_dots(size.width_mm, dpi)
			h_dots = _mm_to_dots(size.height_mm, dpi)
			pcx_data, png_data = _html_to_image(rendered_html, w_dots, h_dots)
			frappe.logger("label_printer").info(f"PCX: {len(pcx_data)} bytes")

			is_mock = printer.mock_printing

			if not is_mock:
				_send_pcx_label(printer, pcx_data, size, copies=job.copies or 1)
			else:
				frappe.logger("label_printer").info(f"Mock printing — skipped sending to printer")

			status_note = "[MOCK] " if is_mock else ""
			frappe.db.set_value("Print Job", print_job_name, {
				"status": "Printed",
				"printed_at": now_datetime(),
				"zpl_output": f"{status_note}[HTML template rendered to PCX, {len(pcx_data)} bytes]",
				"error_message": "",
			})

			_save_preview_image(print_job_name, png_data)
		else:
			ezpl = _render_template(template, doc=ref_doc, data=raw_data, parent_doc=parent_doc)
			frappe.logger("label_printer").info(
				f"Rendered EZPL ({len(ezpl)} chars): {repr(ezpl[:200])}"
			)

			if not ezpl or not ezpl.strip():
				raise ValueError("Template rendered empty EZPL output")

			is_mock = printer.mock_printing

			if not is_mock:
				for i in range(job.copies or 1):
					frappe.logger("label_printer").info(
						f"Sending copy {i+1}/{job.copies or 1} to {printer.ip_address}:{printer.port}"
					)
					_send_ezpl(printer, ezpl)
			else:
				frappe.logger("label_printer").info(f"Mock printing — skipped sending to printer")

			status_note = "[MOCK] " if is_mock else ""
			frappe.db.set_value("Print Job", print_job_name, {
				"status": "Printed",
				"printed_at": now_datetime(),
				"zpl_output": f"{status_note}{ezpl}",
				"error_message": "",
			})
		frappe.logger("label_printer").info(f"Print job {print_job_name} completed successfully")
		return {"success": True, "print_job": print_job_name}
	except Exception as e:
		import traceback
		tb = traceback.format_exc()
		frappe.logger("label_printer").error(f"Print job {print_job_name} failed: {e}\n{tb}")
		frappe.db.set_value("Print Job", print_job_name, {
			"status": "Failed",
			"error_message": str(e),
		})
		frappe.throw(_("Print failed: {0}").format(str(e)))


def _render_template(template_doc, doc=None, data=None, parent_doc=None):
	if template_doc.template_type == "EZPL":
		return _render_ezpl_template(template_doc, doc=doc, data=data, parent_doc=parent_doc)
	elif template_doc.template_type == "HTML":
		return _render_html_template(template_doc, doc=doc, data=data, parent_doc=parent_doc)
	else:
		frappe.throw(_("Unsupported template type: {0}").format(template_doc.template_type))


def _render_html_template(template_doc, doc=None, data=None, parent_doc=None):
	from erpnext.manufacturing.doctype.label_template.label_template import render_html_template
	return render_html_template(template_doc, doc=doc, data=data, parent_doc=parent_doc)


def _html_to_pcx(html, width_px, height_px):
	from erpnext.manufacturing.doctype.label_template.label_template import html_to_pcx_bytes
	return html_to_pcx_bytes(html, width_px, height_px)


def _html_to_image(html, width_px, height_px):
	from erpnext.manufacturing.doctype.label_template.label_template import html_to_image
	return html_to_image(html, width_px, height_px)


def _save_preview_image(print_job_name, png_data):
	try:
		filename = f"{print_job_name}.png"
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": filename,
			"attached_to_doctype": "Print Job",
			"attached_to_name": print_job_name,
			"attached_to_field": "preview_image",
			"content": png_data,
			"is_private": 1,
		})
		file_doc.save(ignore_permissions=True)
		frappe.db.set_value("Print Job", print_job_name, "preview_image", file_doc.file_url)
	except Exception:
		frappe.logger("label_printer").warning(f"Failed to save preview image for {print_job_name}", exc_info=True)


def _send_pcx_label(printer_doc, pcx_data, size_doc, copies=1):
	import uuid

	ox = int(getattr(printer_doc, "offset_x", 0) or 0)
	oy = int(getattr(printer_doc, "offset_y", 0) or 0)
	timeout = printer_doc.timeout or 5

	for i in range(copies):
		name = uuid.uuid4().hex[:8].upper()

		parts = []
		parts.append(f"~EK,{name}\r\n".encode("ascii"))
		parts.append(f"~EP,{name},{len(pcx_data)}\r\n".encode("ascii"))
		parts.append(pcx_data)
		parts.append(b"\r\n")
		parts.append(f"^W{int(size_doc.width_mm)}\r\n".encode("ascii"))
		parts.append(b"^E13\r\n")
		parts.append(b"^L\r\n")
		parts.append(f"Y{ox},{oy},{name}\r\n".encode("ascii"))
		parts.append(b"E\r\n")
		parts.append(f"~EK,{name}\r\n".encode("ascii"))

		payload = b"".join(parts)
		frappe.logger("label_printer").info(
			f"_send_pcx_label: name={name}, copy {i+1}/{copies}, {len(payload)} bytes"
		)
		_tcp_send_raw(printer_doc.ip_address, printer_doc.port, payload, timeout)


def _render_ezpl_template(template_doc, doc=None, data=None, parent_doc=None):
	context = {"frappe": frappe, "_": _}

	if doc:
		context["doc"] = doc
	elif data:
		if isinstance(data, str):
			data = json.loads(data)
		context["doc"] = frappe._dict(data)
	else:
		context["doc"] = frappe._dict()

	if parent_doc:
		context["parent"] = parent_doc

	template_str = template_doc.zpl_template or ""
	frappe.logger("label_printer").info(
		f"_render_ezpl_template: template={template_doc.name}, "
		f"template_len={len(template_str)}, has_doc={doc is not None}, "
		f"template_preview={repr(template_str[:100])}"
	)

	result = frappe.render_template(template_str, context)
	frappe.logger("label_printer").info(
		f"_render_ezpl_template: rendered {len(result)} chars: {repr(result[:200])}"
	)
	return result


# ---------------------------------------------------------------------------
# Whitelisted API — queue management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_print_job(label_template, printer_name, reference_name=None, raw_data=None, copies=1):
	template = frappe.get_doc("Label Template", label_template)

	job = frappe.new_doc("Print Job")
	job.label_template = label_template
	job.label_printer = printer_name
	job.label_size = template.label_size
	job.reference_doctype = template.reference_doctype
	job.reference_name = reference_name
	job.copies = int(copies) or 1
	job.status = "Queued"
	if raw_data:
		if isinstance(raw_data, str):
			job.raw_data = raw_data
		else:
			job.raw_data = json.dumps(raw_data, ensure_ascii=False)
	job.insert()

	return {"print_job": job.name}


@frappe.whitelist()
def cancel_print_job(print_job_name):
	job = frappe.get_doc("Print Job", print_job_name)
	if job.status == "Queued":
		frappe.db.set_value("Print Job", print_job_name, "status", "Cancelled")
		return {"success": True}
	frappe.throw(_("Can only cancel queued jobs"))


@frappe.whitelist()
def batch_print_jobs(job_names):
	job_names = json.loads(job_names)
	results = {"printed": 0, "failed": 0}
	for name in job_names:
		try:
			print_label(name)
			results["printed"] += 1
		except Exception:
			results["failed"] += 1
	return results


@frappe.whitelist()
def batch_cancel_jobs(job_names):
	job_names = json.loads(job_names)
	cancelled = 0
	for name in job_names:
		status = frappe.db.get_value("Print Job", name, "status")
		if status == "Queued":
			frappe.db.set_value("Print Job", name, "status", "Cancelled")
			cancelled += 1
	frappe.db.commit()
	return {"cancelled": cancelled}


@frappe.whitelist()
def batch_delete_jobs(job_names):
	job_names = json.loads(job_names)
	deleted = 0
	for name in job_names:
		frappe.delete_doc("Print Job", name, force=True, delete_permanently=True)
		deleted += 1
	frappe.db.commit()
	return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Whitelisted API — label change
# ---------------------------------------------------------------------------

@frappe.whitelist()
def start_label_change(printer_name, new_label_size, message=None):
	frappe.db.set_value("Label Printer", printer_name, {
		"is_label_change_in_progress": 1,
		"label_change_message": message or _("Changing labels..."),
		"pending_label_size": new_label_size,
	})
	return {"success": True}


@frappe.whitelist()
def cancel_label_change(printer_name):
	frappe.db.set_value("Label Printer", printer_name, {
		"is_label_change_in_progress": 0,
		"label_change_message": "",
		"pending_label_size": "",
	})
	return {"success": True}


@frappe.whitelist()
def complete_label_change(printer_name, new_label_size):
	frappe.db.set_value("Label Printer", printer_name, {
		"is_label_change_in_progress": 0,
		"label_change_message": "",
		"pending_label_size": "",
		"loaded_label_size": new_label_size,
	})

	try:
		_refresh_printer_info(printer_name)
	except Exception:
		frappe.logger("label_printer").warning(
			f"Could not refresh printer info after label change for {printer_name}", exc_info=True
		)

	queued_jobs = frappe.get_all(
		"Print Job",
		filters={
			"label_printer": printer_name,
			"status": "Queued",
			"label_size": ["!=", new_label_size],
		},
		pluck="name",
	)
	for job_name in queued_jobs:
		frappe.db.set_value("Print Job", job_name, {
			"status": "Cancelled",
			"error_message": _("Cancelled: label size changed to {0}").format(new_label_size),
		})

	return {"success": True, "cancelled_jobs": len(queued_jobs)}


# ---------------------------------------------------------------------------
# Whitelisted API — queue list / printers list
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_queue(printer_name=None, status=None):
	filters = {}
	if printer_name:
		filters["label_printer"] = printer_name
	if status:
		filters["status"] = status

	return frappe.get_all(
		"Print Job",
		filters=filters,
		fields=[
			"name", "label_template", "label_printer", "label_size",
			"reference_doctype", "reference_name", "status", "copies",
			"creation", "printed_at", "error_message",
		],
		order_by="creation desc",
		limit=100,
	)


@frappe.whitelist()
def get_printers():
	return frappe.get_all(
		"Label Printer",
		filters={"is_enabled": 1},
		fields=[
			"name", "printer_name", "printer_model", "ip_address",
			"loaded_label_size", "is_label_change_in_progress",
			"label_change_message", "last_status",
		],
	)


# ---------------------------------------------------------------------------
# Whitelisted API — batch label printing
# ---------------------------------------------------------------------------

@frappe.whitelist()
def count_labels(source_doctype, source_names, label_template):
	source_names = json.loads(source_names)
	template = frappe.get_doc("Label Template", label_template)

	if not template.source_field:
		frappe.throw(_("Label Template {0} has no Source Field configured").format(label_template))

	total = 0
	details = []
	for name in source_names:
		doc = frappe.get_doc(source_doctype, name)
		raw = doc.get(template.source_field) or ""
		items = [line.strip() for line in raw.strip().split("\n") if line.strip()]
		total += len(items)
		details.append({"name": name, "count": len(items)})

	return {"total": total, "details": details}


@frappe.whitelist()
def print_labels_batch(source_doctype, source_names, label_template, printer_name):
	source_names = json.loads(source_names)
	template = frappe.get_doc("Label Template", label_template)

	if not template.source_field:
		frappe.throw(_("Label Template {0} has no Source Field configured").format(label_template))

	jobs = []
	for source_name in source_names:
		source_doc = frappe.get_doc(source_doctype, source_name)
		raw = source_doc.get(template.source_field) or ""
		items = [line.strip() for line in raw.strip().split("\n") if line.strip()]

		if not items:
			continue

		for ref_name in items:
			job = frappe.new_doc("Print Job")
			job.label_template = label_template
			job.label_printer = printer_name
			job.label_size = template.label_size
			job.reference_doctype = template.reference_doctype
			job.reference_name = ref_name
			job.parent_doctype = source_doctype
			job.parent_name = source_name
			job.copies = 1
			job.status = "Queued"
			job.insert()
			jobs.append(job.name)

	frappe.db.commit()
	return {"jobs": jobs, "count": len(jobs)}


def cleanup_old_print_jobs(days=7):
	"""Delete Printed/Failed/Cancelled print jobs older than `days` days.
	Intended to be called daily via Scheduled Job Type."""
	from frappe.utils import add_days, today

	cutoff = add_days(today(), -days)
	old_jobs = frappe.get_all(
		"Print Job",
		filters={
			"status": ["in", ["Printed", "Failed", "Cancelled"]],
			"creation": ["<", cutoff],
		},
		fields=["name"],
		limit_page_length=500,
	)
	for job in old_jobs:
		frappe.delete_doc("Print Job", job.name, force=True, delete_permanently=True)

	if old_jobs:
		frappe.db.commit()
		frappe.logger("label_printer").info(f"Cleaned up {len(old_jobs)} old print jobs (older than {cutoff})")
