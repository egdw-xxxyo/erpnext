import frappe
from frappe import _
from frappe.model.document import Document


class PrintJob(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		copies: DF.Int
		created_by_user: DF.Link | None
		error_message: DF.SmallText | None
		label_printer: DF.Link | None
		label_size: DF.Link | None
		label_template: DF.Link | None
		naming_series: DF.Literal["PJ-.#####"]
		parent_doctype: DF.Link | None
		parent_name: DF.DynamicLink | None
		preview_image: DF.AttachImage | None
		printed_at: DF.Datetime | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		status: DF.Literal["Queued", "Printing", "Printed", "Failed", "Cancelled"]
		zpl_output: DF.Code | None

	def validate(self):
		pass

	def on_trash(self):
		frappe.db.delete("File", {
			"attached_to_doctype": "Print Job",
			"attached_to_name": self.name,
		})
