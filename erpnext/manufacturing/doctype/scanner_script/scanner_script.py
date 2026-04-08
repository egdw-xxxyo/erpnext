import frappe
from frappe.model.document import Document


class ScannerScript(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		is_active: DF.Check
		script: DF.Code | None
		script_name: DF.Data | None
		workplace: DF.Link | None
