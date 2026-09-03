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
		log: DF.Code | None

	def validate(self):
		pass

	def on_trash(self):
		file_names = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Print Job",
				"attached_to_name": self.name,
			},
			pluck="name",
		)
		for file_name in file_names:
			frappe.delete_doc(
				"File",
				file_name,
				force=True,
				ignore_permissions=True,
				delete_permanently=True,
			)


def cleanup_old_print_jobs(days=7, batch_size=5000):
	"""Daily scheduler job: delete finished Print Jobs older than `days`
	along with their attached preview/PCX files."""
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -days)
	job_names = frappe.get_all(
		"Print Job",
		filters={
			"status": ["in", ["Printed", "Cancelled"]],
			"modified": ["<", cutoff],
		},
		pluck="name",
		limit_page_length=batch_size,
	)
	for i, name in enumerate(job_names):
		try:
			frappe.delete_doc(
				"Print Job",
				name,
				force=True,
				ignore_permissions=True,
				delete_permanently=True,
			)
		except Exception:
			frappe.logger("label_printer").warning(f"Failed to clean up Print Job {name}", exc_info=True)
		if i % 100 == 0:
			frappe.db.commit()
	frappe.db.commit()
	return len(job_names)
