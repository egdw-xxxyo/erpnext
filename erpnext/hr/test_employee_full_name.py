import unittest

import frappe

from erpnext.hr.employee_full_name import EmployeeFullName, user_name_parts


class TestEmployeeFullName(unittest.TestCase):
	def test_full_name_is_last_first_middle(self):
		doc = frappe._dict(first_name="Тарас", middle_name="Григорович", last_name="Шевченко")

		EmployeeFullName.set_employee_name(doc)

		self.assertEqual(doc.employee_name, "Шевченко Тарас Григорович")

	def test_missing_parts_are_skipped(self):
		doc = frappe._dict(first_name="Тарас", middle_name="", last_name="Шевченко")

		EmployeeFullName.set_employee_name(doc)

		self.assertEqual(doc.employee_name, "Шевченко Тарас")

	def test_user_gets_name_parts_not_a_split_string(self):
		employee = frappe._dict(first_name="Тарас", middle_name=None, last_name="Шевченко")

		self.assertEqual(
			user_name_parts(employee),
			{"first_name": "Тарас", "middle_name": "", "last_name": "Шевченко"},
		)
