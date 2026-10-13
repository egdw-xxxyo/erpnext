import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class PackingJob(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.manufacturing.doctype.packing_job_serial.packing_job_serial import PackingJobSerial

		box_no: DF.Int
		box_total: DF.Int
		consumption_entry: DF.Link | None
		employee: DF.Link | None
		finished_on: DF.Datetime | None
		production_line: DF.Link | None
		recipe: DF.Link | None
		serials: DF.Table[PackingJobSerial]
		started_on: DF.Datetime | None
		status: DF.Literal["In Progress", "Done", "Cancelled"]
		stock_entry: DF.Link | None
		units_per_box: DF.Int
		workplace: DF.Link | None

	def validate(self):
		if not self.started_on:
			self.started_on = now_datetime()

		seen = set()
		for row in self.serials:
			if row.serial_no in seen:
				frappe.throw(_("Serial No {0} is listed more than once").format(row.serial_no))
			seen.add(row.serial_no)

		if self.status == "In Progress":
			busy = frappe.get_all(
				"Packing Job Serial",
				filters={
					"serial_no": ["in", list(seen)],
					"parenttype": "Packing Job",
					"parent": ["!=", self.name or ""],
				},
				fields=["serial_no", "parent"],
			)
			busy = [
				row
				for row in busy
				if frappe.db.get_value("Packing Job", row.parent, "status") == "In Progress"
			]
			if busy:
				frappe.throw(
					_("Already in an open packing job: {0}").format(
						", ".join(f"{row.serial_no} ({row.parent})" for row in busy)
					)
				)
