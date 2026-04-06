import frappe
from frappe.model.document import Document


class ScannerSetup(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data | None
		api_key_preview: DF.Data | None
		is_active: DF.Check
		scanner_name: DF.Data | None
		users: DF.Table["ScannerSetupUser"]

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

	frappe.msgprint(
		f"New API Key: <code>{key}</code><br><br>Copy it now — it won't be shown again.",
		title="API Key Regenerated",
		indicator="green",
	)

	return preview
