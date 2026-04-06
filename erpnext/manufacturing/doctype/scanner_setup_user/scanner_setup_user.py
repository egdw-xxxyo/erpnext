import frappe
from frappe.model.document import Document


class ScannerSetupUser(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		full_name: DF.Data | None
		user: DF.Link | None
