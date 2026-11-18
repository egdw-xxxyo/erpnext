from frappe.model.document import Document


class ProductionLineAllowedItem(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		bom_no: DF.Link | None
		can_produce: DF.Int
		item_code: DF.Link
		item_name: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
