import hashlib
import hmac
import secrets

import frappe
from frappe.model.document import Document


def _get_scanner_secret():
	secret = frappe.conf.get("scanner_secret")
	if not secret:
		frappe.throw(
			"scanner_secret is not set in site_config.json. Run: bench set-config scanner_secret <your-secret>"
		)
	return secret


def compute_auth_token(api_key):
	secret = _get_scanner_secret()
	return hmac.new(secret.encode(), api_key.encode(), hashlib.sha256).hexdigest()[:16]


MAX_SCAN_LOGS = 100


def _next_scan_log_idx(scanner_name):
	return (
		frappe.db.sql(
			"""SELECT IFNULL(MAX(idx), 0) FROM `tabScanner Scan Log Entry`
			WHERE parent = %s AND parenttype = 'Scanner'""",
			scanner_name,
		)[0][0]
		+ 1
	)


def cleanup_scan_logs():
	"""Keep only the newest MAX_SCAN_LOGS rows per scanner. Runs hourly.

	idx is monotonically increasing per scanner (append-only), so "newest" is
	simply the highest idx values.
	"""
	frappe.db.sql(
		"""DELETE t FROM `tabScanner Scan Log Entry` t
		JOIN (
			SELECT parent, MAX(idx) AS max_idx
			FROM `tabScanner Scan Log Entry`
			WHERE parenttype = 'Scanner'
			GROUP BY parent
		) x ON x.parent = t.parent
		WHERE t.parenttype = 'Scanner' AND t.idx <= x.max_idx - %s""",
		MAX_SCAN_LOGS,
	)
	frappe.db.commit()


class Scanner(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.devices.doctype.scanner_scan_log_entry.scanner_scan_log_entry import (
			ScannerScanLogEntry,
		)

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
		return frappe._dict(
			idle_timeout=3600,
			state_timeout=300,
			display_rows=10,
			display_chars_per_row=20,
			message_template="",
		)

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
		"""Append one scan log row without touching the parent doc.

		`self.save()` here used to rewrite the whole scan_logs table on every scan
		(~150ms at the 100-row cap, twice per scan). Rows are append-only now and
		trimmed by the hourly `cleanup_scan_logs` job instead.
		"""
		row = frappe.get_doc(
			{
				"doctype": "Scanner Scan Log Entry",
				"parent": self.name,
				"parenttype": "Scanner",
				"parentfield": "scan_logs",
				"idx": _next_scan_log_idx(self.name),
				**kwargs,
			}
		)
		row.db_insert()
		return row.name

	def update_scan_log(self, row_name, **kwargs):
		updates = {k: v for k, v in kwargs.items() if v is not None}
		if updates:
			frappe.db.set_value("Scanner Scan Log Entry", row_name, updates, update_modified=False)


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
		from io import BytesIO

		import barcode
		from barcode.writer import SVGWriter

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
	from urllib.parse import urlparse

	from erpnext.devices.doctype.otdr.otdr_api import detect_public_base_url

	doc = frappe.get_doc("Scanner", scanner_name)
	doc.check_permission("read")

	# Client sends window.location.origin — replace if it's a non-LAN host (localhost, Docker internal).
	try:
		parsed = urlparse(endpoint_url)
		host = (parsed.hostname or "").lower()
		bad = (
			host in ("", "localhost", "127.0.0.1")
			or host.startswith("frontend")
			or host.startswith("backend")
		)
		if bad:
			public = detect_public_base_url().rstrip("/")
			endpoint_url = public + parsed.path
	except Exception:
		pass

	api_key = frappe.db.get_value("Scanner", scanner_name, "api_key")
	payload = f"CFG-SCANNER?url={endpoint_url}&key={api_key}"

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
