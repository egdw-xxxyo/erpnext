import frappe
from frappe.model.document import Document


class Workplace(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed_employees: DF.Table["WorkplaceEmployee"]
		allowed_operations: DF.Table["WorkplaceOperation"]
		barcode: DF.Data | None
		company: DF.Link | None
		description: DF.SmallText | None
		is_active: DF.Check
		workplace_name: DF.Data | None

	def before_insert(self):
		if not self.barcode:
			self.barcode = f"WP-{frappe.generate_hash(length=8).upper()}"
