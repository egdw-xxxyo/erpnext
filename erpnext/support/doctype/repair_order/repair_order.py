from frappe.model.document import Document


class RepairOrder(Document):
	def validate(self):
		from erpnext.support.service_repair import validate_order

		validate_order(self)

	def on_update(self):
		from erpnext.support.service_repair import order_updated

		order_updated(self)
