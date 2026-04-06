import frappe
from frappe.model.document import Document


class ScannerSetup(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data | None
		api_key_preview: DF.Data | None
		employee: DF.Link | None
		idle_timeout: DF.Int
		is_active: DF.Check
		scanner_name: DF.Data | None
		workplace: DF.Link | None

	def before_insert(self):
		self._generate_api_key()

	def _generate_api_key(self):
		import secrets

		key = secrets.token_hex(32)
		self.api_key = key
		self.api_key_preview = "••••" + key[-4:]

	def onload(self):
		if self.api_key:
			self.api_key_preview = "••••" + self.api_key[-4:]
			self.api_key = ""


@frappe.whitelist()
def get_api_key(scanner_name):
	doc = frappe.get_doc("Scanner Setup", scanner_name)
	doc.check_permission("write")
	return frappe.db.get_value("Scanner Setup", scanner_name, "api_key")


@frappe.whitelist()
def regenerate_api_key(scanner_name):
	import secrets

	doc = frappe.get_doc("Scanner Setup", scanner_name)
	doc.check_permission("write")

	key = secrets.token_hex(32)
	preview = "••••" + key[-4:]
	frappe.db.set_value("Scanner Setup", scanner_name, {
		"api_key": key,
		"api_key_preview": preview,
	})
	frappe.db.commit()

	qr_svg = _make_qr_svg(key)

	return {"preview": preview, "key": key, "qr_svg": qr_svg}


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
