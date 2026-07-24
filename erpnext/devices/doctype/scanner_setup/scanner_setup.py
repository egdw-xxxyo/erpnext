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


class ScannerSetup(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data | None
		employee: DF.Link | None
		idle_timeout: DF.Int
		is_active: DF.Check
		scanner_name: DF.Data | None
		workplace: DF.Link | None

	def before_insert(self):
		if not self.api_key:
			self.api_key = secrets.token_hex(4)

	def onload(self):
		if self.api_key:
			self.set_onload("qr_svg", _make_qr_svg(self.api_key))


@frappe.whitelist()
def regenerate_api_key(scanner_name):
	doc = frappe.get_doc("Scanner Setup", scanner_name)
	doc.check_permission("write")

	key = secrets.token_hex(4)
	frappe.db.set_value("Scanner Setup", scanner_name, "api_key", key)
	frappe.db.commit()

	return {"api_key": key, "qr_svg": _make_qr_svg(key)}


@frappe.whitelist()
def get_scanner_key(scanner_name):
	doc = frappe.get_doc("Scanner Setup", scanner_name)
	doc.check_permission("read")
	api_key = frappe.db.get_value("Scanner Setup", scanner_name, "api_key")
	return compute_auth_token(api_key)


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
	doc = frappe.get_doc("Scanner Setup", scanner_name)
	doc.check_permission("read")

	api_key = frappe.db.get_value("Scanner Setup", scanner_name, "api_key")

	return {
		"cfg_url_barcode": render_barcode_svg("CFG-URL"),
		"url_qr": _make_qr_svg(endpoint_url),
		"cfg_key_barcode": render_barcode_svg("CFG-KEY"),
		"api_key_qr": _make_qr_svg(api_key),
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
