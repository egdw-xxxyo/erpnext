from frappe.model.document import Document


class WorkplaceScriptContextField(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app_editable: DF.Check
		blocks_switch: DF.Check
		description: DF.SmallText | None
		enter_state: DF.Data | None
		fieldtype: DF.Literal["Data", "Int", "Float", "Check", "Link", "Select"]
		is_primary: DF.Check
		key: DF.Data
		label: DF.Data | None
		link_filters: DF.Code | None
		link_order_by: DF.Data | None
		options: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		preserve_on_switch: DF.Check
		show_in_app: DF.Check
