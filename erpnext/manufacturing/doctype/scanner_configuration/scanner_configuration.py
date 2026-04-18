import frappe
from frappe.model.document import Document


class ScannerConfiguration(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		configuration_name: DF.Data | None
		display_rows: DF.Int
		display_chars_per_row: DF.Int
		idle_timeout: DF.Int
		message_template: DF.SmallText | None
