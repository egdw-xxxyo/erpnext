import frappe
from frappe.model.document import Document


class FlashAttempt(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		console_line: DF.SmallText | None
		employee: DF.Link | None
		failure_reason: DF.SmallText | None
		finished_on: DF.Datetime | None
		firmware: DF.Link | None
		firmware_version: DF.Link | None
		flashing_profile: DF.Link | None
		image_sha256: DF.Data | None
		job_card: DF.Link
		serial_no: DF.Data | None
		started_on: DF.Datetime | None
		status: DF.Literal["In Progress", "Done", "Failed", "Released"]
		verified_by: DF.Literal["", "Console", "Operator"]
		workplace: DF.Link | None
