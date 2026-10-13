from erpnext.payroll_ua.employee_names import get_full_name


class EmployeeFullName:
	def set_employee_name(self):
		self.employee_name = get_full_name(self)


def user_name_parts(employee) -> dict:
	return {
		"first_name": employee.first_name,
		"middle_name": employee.middle_name or "",
		"last_name": employee.last_name or "",
	}
