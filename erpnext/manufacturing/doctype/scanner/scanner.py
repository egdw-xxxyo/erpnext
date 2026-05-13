import hashlib
import hmac
import secrets

import frappe
from frappe.model.document import Document


def _get_scanner_secret():
	secret = frappe.conf.get("scanner_secret")
	if not secret:
		frappe.throw("scanner_secret is not set in site_config.json. Run: bench set-config scanner_secret <your-secret>")
	return secret


def compute_auth_token(api_key):
	secret = _get_scanner_secret()
	return hmac.new(
		secret.encode(), api_key.encode(), hashlib.sha256
	).hexdigest()[:16]


MAX_SCAN_LOGS = 100


class Scanner(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data | None
		employee: DF.Link | None
		is_active: DF.Check
		scanner_configuration: DF.Link | None
		scanner_name: DF.Data | None
		workplace: DF.Link | None
		scan_logs: DF.Table["ScannerScanLogEntry"]

	def get_configuration(self):
		if self.scanner_configuration:
			return frappe.get_cached_doc("Scanner Configuration", self.scanner_configuration)
		return frappe._dict(idle_timeout=3600, state_timeout=300, display_rows=10, display_chars_per_row=20, message_template="")

	def get_state_timeout(self):
		config = self.get_configuration()
		return config.get("state_timeout") or 300

	def before_insert(self):
		if not self.api_key:
			self.api_key = secrets.token_hex(4)

	def onload(self):
		if self.api_key:
			self.set_onload("qr_svg", _make_qr_svg(self.api_key))

	def add_scan_log(self, **kwargs):
		row = self.append("scan_logs", kwargs)
		self.scan_logs.remove(row)
		self.scan_logs.insert(0, row)
		if len(self.scan_logs) > MAX_SCAN_LOGS:
			self.scan_logs = self.scan_logs[:MAX_SCAN_LOGS]
		for i, r in enumerate(self.scan_logs):
			r.idx = i + 1
		self.flags.ignore_permissions = True
		self.save()
		return row.name

	def update_scan_log(self, row_name, **kwargs):
		for row in self.scan_logs:
			if row.name == row_name:
				for key, val in kwargs.items():
					if val is not None:
						row.set(key, val)
				break
		self.flags.ignore_permissions = True
		self.save()


@frappe.whitelist()
def regenerate_api_key(scanner_name):
	doc = frappe.get_doc("Scanner", scanner_name)
	doc.check_permission("write")

	key = secrets.token_hex(4)
	frappe.db.set_value("Scanner", scanner_name, "api_key", key)
	frappe.db.commit()

	return {"api_key": key, "qr_svg": _make_qr_svg(key)}


@frappe.whitelist()
def get_scanner_key(scanner_name):
	doc = frappe.get_doc("Scanner", scanner_name)
	doc.check_permission("read")
	api_key = frappe.db.get_value("Scanner", scanner_name, "api_key")
	return compute_auth_token(api_key)


@frappe.whitelist()
def get_display_config(scanner_name):
	doc = frappe.get_doc("Scanner", scanner_name)
	doc.check_permission("read")
	config = doc.get_configuration()
	return {
		"rows": config.display_rows or 10,
		"cols": config.display_chars_per_row or 20,
	}


@frappe.whitelist()
def render_barcode_svg(data):
	try:
		import barcode
		from barcode.writer import SVGWriter
		from io import BytesIO

		code128 = barcode.get_barcode_class("code128")
		writer = SVGWriter()
		bc = code128(data, writer=writer)
		stream = BytesIO()
		bc.write(stream, {"module_width": 0.4, "module_height": 12, "font_size": 10, "text_distance": 5})
		svg = stream.getvalue().decode()
		stream.close()
		return svg
	except Exception:
		return f'<code style="font-size: 14px; letter-spacing: 1px;">{frappe.utils.escape_html(data)}</code>'


@frappe.whitelist()
def get_config_barcodes(scanner_name, endpoint_url):
	from urllib.parse import urlencode

	doc = frappe.get_doc("Scanner", scanner_name)
	doc.check_permission("read")

	api_key = frappe.db.get_value("Scanner", scanner_name, "api_key")
	payload = "CFG-SCANNER?" + urlencode({"url": endpoint_url, "key": api_key})

	return {
		"config_qr": _make_qr_svg(payload),
		"config_payload": payload,
		"endpoint_url": endpoint_url,
		"api_key": api_key,
	}


@frappe.whitelist()
def render_qr_svg(data):
	return _make_qr_svg(data)


def _make_qr_svg(data):
	from io import BytesIO

	from pyqrcode import create as qrcreate

	qr = qrcreate(data)
	stream = BytesIO()
	try:
		qr.svg(stream, scale=4, background="#fff", module_color="#222")
		return stream.getvalue().decode().replace("\n", "")
	finally:
		stream.close()
