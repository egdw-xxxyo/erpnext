# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One reflectometer trace, kept as a document.

Measurements used to live in a 100-row FIFO child table on the OTDR device record, holding
the parsed trace as an opaque JSON blob with no link to the spool. That answered "what did
this device do lately" and nothing else — in particular it could not answer "show every
measurement taken on this spool", which is the question asked when a spool is rejected.

So the record is per-measurement and keyed on `serial_no`: a spool measured three times has
three rows, and `serial_no_dashboard` surfaces them in the Serial No form's Connections.
"""

import frappe
from frappe.model.document import Document


class OTDRMeasurement(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		distance_km: DF.Float
		employee: DF.Link | None
		error_message: DF.SmallText | None
		filename: DF.Data | None
		item_code: DF.Link | None
		loss_db: DF.Float
		measured_on: DF.Datetime | None
		measurement_type: DF.Literal["SOR", "OPM", "VFL"]
		naming_series: DF.Literal["OM-.#####"]
		orl_db: DF.Float
		payload: DF.Code | None
		print_job: DF.Link | None
		quality_inspection: DF.Link | None
		remote_path: DF.Data | None
		script_log: DF.Code | None
		script_state: DF.Data | None
		serial_no: DF.Link | None
		sor_file: DF.Data | None
		status: DF.Literal["Success", "Error"]
		verdict: DF.Literal["", "Pass", "Fail", "Undetermined"]
		wavelength_nm: DF.Float
		workplace: DF.Link | None

	def before_insert(self):
		if not self.measured_on:
			self.measured_on = frappe.utils.now_datetime()
