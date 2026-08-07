import frappe
from frappe.model.document import Document


class OTDRConfiguration(Document):
	def on_update(self):
		from erpnext.devices.doctype.otdr.otdr import publish_config

		linked = frappe.get_all(
			"OTDR",
			filters={"otdr_configuration": self.name, "is_active": 1},
			fields=["name"],
		)
		for row in linked:
			try:
				publish_config(row.name)
			except Exception:
				frappe.log_error(title="OTDR Configuration: publish_config failed")
