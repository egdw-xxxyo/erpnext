import frappe
from frappe.model.document import Document


class WorkplaceScript(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		is_active: DF.Check
		script: DF.Code | None
		script_name: DF.Data | None
		workplace: DF.Link | None

	def validate(self):
		if not self.is_active:
			return

		filters = {"is_active": 1, "name": ["!=", self.name]}
		if self.workplace:
			filters["workplace"] = self.workplace
			existing = frappe.db.exists("Workplace Script", filters)
			if existing:
				frappe.throw(
					f"An active Workplace Script already exists for workplace {self.workplace}: {existing}"
				)
		else:
			filters["workplace"] = ["is", "not set"]
			existing = frappe.db.exists("Workplace Script", filters)
			if existing:
				frappe.throw(
					f"An active default Workplace Script (no workplace) already exists: {existing}"
				)
