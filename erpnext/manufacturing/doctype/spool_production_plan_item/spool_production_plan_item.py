import frappe
from frappe.model.document import Document


class SpoolProductionPlanItem(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		daily_qty: DF.Int
		enabled: DF.Check
		item_code: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		workplace: DF.Link | None
