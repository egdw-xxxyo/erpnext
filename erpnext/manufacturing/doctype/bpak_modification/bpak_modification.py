import frappe
from frappe import _
from frappe.model.document import Document


class BpAKModification(Document):
	def validate(self):
		existing = frappe.db.get_value(
			"BpAK Modification",
			{
				"specification": self.specification,
				"modification_number": self.modification_number,
				"name": ("!=", self.name),
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("Модифікація {0} вже існує для специфікації {1}: {2}").format(
					self.modification_number, self.specification, existing
				)
			)
