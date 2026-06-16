import frappe
from frappe import _
from frappe.model.document import Document


class Pallet(Document):
	def validate(self):
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		if not self._linked_package_count():
			frappe.throw(_("Cannot submit an empty Pallet. Add packages first."))

	def on_submit(self):
		self.db_set("status", "Packed")
		self._update_so_progress()

	def on_cancel(self):
		frappe.db.sql(
			"UPDATE `tabPackage` SET pallet = NULL WHERE pallet = %s",
			self.name,
		)
		self.db_set("status", "Cancelled")
		self._update_so_progress()

	def _update_so_progress(self):
		if not self.get("sales_order"):
			return
		from erpnext.selling.doctype.sales_order.progress import update_so_progress
		update_so_progress(self.sales_order)

	def on_trash(self):
		if self._linked_package_count():
			frappe.throw(
				_("Cannot delete Pallet {0}: packages are still linked").format(self.name)
			)

	def _linked_package_count(self):
		return frappe.db.count("Package", {"pallet": self.name, "docstatus": ["<", 2]})
