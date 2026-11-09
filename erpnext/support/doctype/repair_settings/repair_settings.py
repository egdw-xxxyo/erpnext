import frappe
from frappe import _
from frappe.model.document import Document


class RepairSettings(Document):
	def validate(self):
		seen = set()
		for row in self.warehouses:
			if row.company in seen:
				frappe.throw(_("Select only one repair warehouse per company."))
			seen.add(row.company)
			warehouse = frappe.get_doc("Warehouse", row.warehouse)
			warehouse.check_permission("read")
			if warehouse.company != row.company or warehouse.is_group or warehouse.disabled:
				frappe.throw(_("Choose an active non-group warehouse of the repair company."))
