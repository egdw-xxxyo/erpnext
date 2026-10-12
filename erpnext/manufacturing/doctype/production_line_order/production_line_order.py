from frappe.model.document import Document


class ProductionLineOrder(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		item_code: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		produced_qty: DF.Int
		qty: DF.Int
		work_order: DF.Link | None
		workplace: DF.Link
