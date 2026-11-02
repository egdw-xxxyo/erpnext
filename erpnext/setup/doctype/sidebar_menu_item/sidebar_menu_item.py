import frappe
from frappe.model.document import Document


class SidebarMenuItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.core.doctype.has_role.has_role import HasRole
		from frappe.types import DF

		disabled: DF.Check
		icon: DF.Data | None
		label: DF.Data
		link_to: DF.Data
		link_type: DF.Literal["Page", "DocType", "Report", "Workspace", "URL"]
		required_doctype: DF.Link | None
		roles: DF.Table[HasRole]
		sidebar: DF.Link | None
		sort_order: DF.Int
	# end: auto-generated types

	def on_update(self):
		frappe.clear_cache()

	def on_trash(self):
		frappe.clear_cache()
