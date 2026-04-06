import frappe
from frappe.model.document import Document


class ScannerCommand(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		barcode: DF.Data | None
		command_name: DF.Data | None
		is_active: DF.Check
		prompt: DF.Data | None
		scanner_action: DF.Link | None
