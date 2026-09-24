import frappe
from frappe.model.document import Document


class WorkplacePrinter(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		ip_address: DF.Data | None
		is_default: DF.Check
		label_printer: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		printer_model: DF.Data | None
		purpose: DF.Data | None
