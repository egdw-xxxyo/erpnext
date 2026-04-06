import frappe
from frappe.model.document import Document


class ScannerScanLog(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		error_message: DF.SmallText | None
		raw_data: DF.Data | None
		resolved_action: DF.Data | None
		result_message: DF.SmallText | None
		scanner: DF.Link | None
		scanner_mode: DF.Data | None
		status: DF.Literal["Processing", "Success", "Error", "Command"]
		target_doctype: DF.Link | None
		target_document: DF.DynamicLink | None
		timestamp: DF.Datetime | None
