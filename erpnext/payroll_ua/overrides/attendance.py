from hrms.hr.doctype.attendance.attendance import Attendance as HrmsAttendance
from hrms.hr.utils import validate_active_employee

from erpnext.controllers.status_updater import validate_status

STATUSES = ["Present", "Absent", "Sick Leave", "On Leave", "Half Day", "Work From Home"]


class Attendance(HrmsAttendance):
	def validate(self):
		"""Upstream's own validate, with a sick day among the statuses it accepts.

		Copied rather than wrapped: the status check runs first and would reject a sick
		day before the rest of the method got to see the document. The method is a list
		of calls and changes about once a year, so the copy is cheap to keep current.
		"""
		validate_status(self.status, STATUSES)
		validate_active_employee(self.employee)
		self.validate_attendance_date()
		self.validate_duplicate_record()
		self.validate_overlapping_shift_attendance()
		self.validate_employee_status()
		self.check_leave_record()
