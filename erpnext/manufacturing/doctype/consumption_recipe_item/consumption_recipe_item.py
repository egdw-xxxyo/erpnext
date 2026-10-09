from frappe.model.document import Document


class ConsumptionRecipeItem(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		condition: DF.Data | None
		item_code: DF.Link
		item_name: DF.Data | None
		notes: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		qty_formula: DF.Data
		source_warehouse: DF.Link | None
		uom: DF.Link | None
