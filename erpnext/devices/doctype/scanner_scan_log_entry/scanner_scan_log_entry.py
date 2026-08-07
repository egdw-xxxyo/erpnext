from frappe.model.document import Document


class ScannerScanLogEntry(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		error_message: DF.SmallText | None
		raw_data: DF.Data | None
		resolved_action: DF.Data | None
		result_message: DF.SmallText | None
		status: DF.Literal["Processing", "Success", "Error", "Command"]
		target_doctype: DF.Link | None
		target_document: DF.DynamicLink | None
		timestamp: DF.Datetime | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
