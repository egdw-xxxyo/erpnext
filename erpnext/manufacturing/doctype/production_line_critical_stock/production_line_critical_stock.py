from frappe.model.document import Document


class ProductionLineCriticalStock(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		critical_qty: DF.Float
		item_code: DF.Link
		item_name: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		stock_uom: DF.Link | None
