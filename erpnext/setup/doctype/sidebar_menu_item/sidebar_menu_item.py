import frappe
from frappe.model.document import Document


class SidebarMenuItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.core.doctype.has_role.has_role import HasRole
		from frappe.types import DF

		builtin: DF.Literal["", "Tasks", "Search", "Scanner", "Notifications"]
		disabled: DF.Check
		icon: DF.Icon | None
		icon_color: DF.Color | None
		label: DF.Data
		link_to: DF.Data | None
		link_type: DF.Literal["Page", "DocType", "Report", "Workspace", "URL"]
		required_doctype: DF.Link | None
		roles: DF.Table[HasRole]
		sidebar: DF.Link | None
		sort_order: DF.Int
	# end: auto-generated types

	def on_trash(self):
		if self.builtin:
			frappe.throw(frappe._("Built-in menu items cannot be deleted, disable them instead."))
		frappe.clear_cache()

	def on_update(self):
		frappe.clear_cache()
