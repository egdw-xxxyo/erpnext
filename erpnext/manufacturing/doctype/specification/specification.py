import frappe
from frappe.model.document import Document

from erpnext.stock.doctype.specification_number_template.specification_number_template import (
	apply_override,
)


class Specification(Document):
	def validate(self):
		self.specification_code = (self.specification_code or "").strip()
		if not self.flags.display_code_set:
			self.display_code = apply_override(self.specification_number_template, self.specification_code)

	def on_update(self):
		if self.has_value_changed("display_code"):
			self.update_linked_items()

	def update_linked_items(self):
		items = frappe.get_all("Item", filters={"specification": self.name}, pluck="name")
		for item in items:
			frappe.db.set_value("Item", item, "specification_code", self.display_code, update_modified=False)


@frappe.whitelist()
def get_display_code(specification):
	if not specification:
		return None
	return frappe.db.get_value("Specification", specification, "display_code")
