from hrms.hr.doctype.leave_application.leave_application import (
	LeaveApplication as HrmsLeaveApplication,
)


class LeaveApplication(HrmsLeaveApplication):
	def validate_for_self_approval(self):
		# the attendance sheet is the one place this does not apply: whoever fills a sheet
		# decides the days in it, and a manager put into their own sheet is no exception
		if self.flags.filed_from_attendance_sheet:
			return

		super().validate_for_self_approval()
