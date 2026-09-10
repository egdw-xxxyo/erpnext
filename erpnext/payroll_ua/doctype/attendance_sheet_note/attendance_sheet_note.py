# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""A note a manager leaves about an employee on the attendance sheet.

It hangs on the employee and carries no period and no manager of its own: whoever fills
the sheet for that employee next reads everything written before them, and a move to
another manager needs nothing done to the notes. No role is granted here on purpose —
the reporting line of the Attendance Sheet page is the only gate, and the whitelisted
methods of that page are where it is checked.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr


class AttendanceSheetNote(Document):
	def validate(self):
		self.note = cstr(self.note).strip()

		if not self.note:
			frappe.throw(_("The note cannot be empty"))
