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
			frappe.throw(_("Cannot delete Pallet {0}: packages are still linked").format(self.name))

	def _linked_package_count(self):
		return frappe.db.count("Package", {"pallet": self.name, "docstatus": ["<", 2]})


def update_status_from_packages(pallet_name):
	"""A submitted pallet is Shipped once every box on it is, Packed otherwise."""
	if frappe.db.get_value("Pallet", pallet_name, "docstatus") != 1:
		return
	statuses = frappe.get_all("Package", filters={"pallet": pallet_name, "docstatus": 1}, pluck="status")
	new_status = "Shipped" if statuses and all(s == "Shipped" for s in statuses) else "Packed"
	if frappe.db.get_value("Pallet", pallet_name, "status") != new_status:
		frappe.db.set_value("Pallet", pallet_name, "status", new_status)
