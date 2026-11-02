from frappe.model.document import Document


class RepairUnit(Document):
	def validate(self):
		from erpnext.support.repair_units import validate_unit

		validate_unit(self)

	def on_update(self):
		from erpnext.support.repair_units import after_unit_update

		after_unit_update(self)
