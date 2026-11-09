import json
import unittest

from erpnext.access_control.sensitive_rules import (
	SETTINGS_DOCTYPE,
	after_failure,
	build_config,
	longest_minutes,
	method_prefixes,
	object_minutes,
	pin_refusal,
	protected_doctype,
	request_target,
	retry_mode,
	settings_delta,
	unlock_end,
	unlocked_until,
)

OBJECTS = [
	{"object_type": "DocType", "object_name": "Payroll Sheet", "unlock_minutes": None},
	{"object_type": "DocType", "object_name": "Salary Change", "unlock_minutes": 5},
	{"object_type": "Report", "object_name": "Salary History", "unlock_minutes": None},
	{"object_type": "Page", "object_name": "payroll-board", "unlock_minutes": None},
]

MODULE_PATHS = {
	("DocType", "Payroll Sheet"): "erpnext.payroll_ua.doctype.payroll_sheet",
	("Report", "Salary History"): "erpnext.payroll_ua.report.salary_history",
	("Page", "payroll-board"): "erpnext.payroll_ua.page.payroll_board",
}

HOOK_METHODS = {
	"Salary History": ["erpnext.payroll_ua.salary_history."],
	"Unprotected Report": ["erpnext.other.method."],
}


def config(**settings):
	return build_config(
		{"enabled": "1", "unlock_minutes": "30", "idle_minutes": "10", "max_attempts": "5", **settings},
		OBJECTS,
		[
			{"document_type": "Employee", "fieldname": "ctc"},
			{"document_type": "Employee", "fieldname": "custom_total_salary"},
		],
		{"Payroll Sheet": ["Payroll Sheet Item"], SETTINGS_DOCTYPE: ["Sensitive Data Object"]},
		{"methods": method_prefixes(OBJECTS, MODULE_PATHS, HOOK_METHODS), "api_users": ["bot@example.com"]},
	)


def target(path, params=None, http_method="POST"):
	return request_target(config(), path, http_method, params or {})


class TestPin(unittest.TestCase):
	def test_six_digits_are_accepted(self):
		self.assertIsNone(pin_refusal("482915"))

	def test_wrong_length_or_letters_are_refused(self):
		for pin in ("12345", "1234567", "12a456", "", None, 123456):
			self.assertEqual(pin_refusal(pin), "format", pin)

	def test_repeated_and_consecutive_digits_are_weak(self):
		for pin in ("000000", "777777", "123456", "456789", "987654", "654321"):
			self.assertEqual(pin_refusal(pin), "weak", pin)


class TestConfig(unittest.TestCase):
	def test_settings_are_typed(self):
		built = config(enabled="0")
		self.assertFalse(built["enabled"])
		self.assertEqual((built["unlock_minutes"], built["idle_minutes"], built["max_attempts"]), (30, 10, 5))

	def test_settings_are_always_protected(self):
		self.assertIn(SETTINGS_DOCTYPE, config()["doctypes"])

	def test_child_tables_follow_their_document(self):
		built = config()
		self.assertEqual(protected_doctype(built, "Payroll Sheet Item"), "Payroll Sheet")
		self.assertEqual(protected_doctype(built, "Sensitive Data Object"), SETTINGS_DOCTYPE)
		self.assertIsNone(protected_doctype(built, "Sales Order"))

	def test_fields_are_grouped_by_document_type(self):
		self.assertEqual(config()["fields"], {"Employee": ["ctc", "custom_total_salary"]})

	def test_object_minutes_fall_back_to_the_default(self):
		built = config()
		self.assertEqual(object_minutes(built, ("DocType", "Salary Change")), 5)
		self.assertEqual(object_minutes(built, ("DocType", "Payroll Sheet")), 30)
		self.assertEqual(object_minutes(built, None), 30)
		self.assertEqual(object_minutes(built, ("Field", "Employee")), 30)

	def test_methods_of_unprotected_objects_are_ignored(self):
		prefixes = [prefix for prefix, _kind, _name in method_prefixes(OBJECTS, MODULE_PATHS, HOOK_METHODS)]
		self.assertNotIn("erpnext.other.method.", prefixes)
		self.assertIn("erpnext.payroll_ua.salary_history.", prefixes)

	def test_config_survives_json(self):
		built = config()
		self.assertEqual(json.loads(json.dumps(built)), built)


class TestRequestTarget(unittest.TestCase):
	def test_form_load(self):
		self.assertEqual(
			target("/api/method/frappe.desk.form.load.getdoc", {"doctype": "Payroll Sheet", "name": "PS-1"}),
			("DocType", "Payroll Sheet"),
		)

	def test_list_of_a_child_table(self):
		self.assertEqual(
			target("/api/method/frappe.client.get_list", {"doctype": "Payroll Sheet Item"}),
			("DocType", "Payroll Sheet"),
		)

	def test_rest_resource(self):
		self.assertEqual(
			target("/api/resource/Salary Change/SC-1", http_method="GET"), ("DocType", "Salary Change")
		)

	def test_save(self):
		doc = json.dumps({"doctype": "Salary Change", "name": "SC-1"})
		self.assertEqual(
			target("/api/method/frappe.desk.form.save.savedocs", {"doc": doc, "action": "Save"}),
			("DocType", "Salary Change"),
		)

	def test_document_method(self):
		docs = json.dumps({"doctype": "Payroll Sheet", "name": "PS-1"})
		self.assertEqual(
			target("/api/method/run_doc_method", {"docs": docs, "method": "refresh_data"}),
			("DocType", "Payroll Sheet"),
		)
		self.assertEqual(
			target("/api/method/run_doc_method", {"dt": "Payroll Sheet", "dn": "PS-1", "method": "pay"}),
			("DocType", "Payroll Sheet"),
		)

	def test_report_run(self):
		self.assertEqual(
			target("/api/method/frappe.desk.query_report.run", {"report_name": "Salary History"}),
			("Report", "Salary History"),
		)
		self.assertIsNone(target("/api/method/frappe.desk.query_report.run", {"report_name": "Stock Ledger"}))

	def test_page_and_doctype_routes(self):
		self.assertEqual(
			target("/api/method/frappe.desk.desk_page.getpage", {"name": "payroll-board"}),
			("Page", "payroll-board"),
		)
		self.assertEqual(
			target("/api/method/frappe.desk.desk_page.getpage", {"name": "payroll-sheet"}),
			("DocType", "Payroll Sheet"),
		)

	def test_methods_in_the_folder_of_a_protected_object(self):
		self.assertEqual(
			target("/api/method/erpnext.payroll_ua.doctype.payroll_sheet.payroll_sheet.get_employees"),
			("DocType", "Payroll Sheet"),
		)
		self.assertEqual(
			target("/api/method/erpnext.payroll_ua.page.payroll_board.payroll_board.get_data"),
			("Page", "payroll-board"),
		)

	def test_declared_methods(self):
		self.assertEqual(
			target("/api/method/erpnext.payroll_ua.salary_history.get_salary_history", {"employee": "E-1"}),
			("Report", "Salary History"),
		)

	def test_unrelated_requests(self):
		self.assertIsNone(target("/api/method/frappe.desk.form.load.getdoc", {"doctype": "Employee"}))
		self.assertIsNone(target("/api/method/erpnext.payroll_ua.attendance_export.download_sheet"))
		self.assertIsNone(target("/app/payroll-sheet", http_method="GET"))

	def test_retry_mode(self):
		self.assertEqual(retry_mode("/api/method/frappe.desk.form.load.getdoc", {}), "reload")
		self.assertEqual(retry_mode("/api/method/frappe.desk.query_report.run", {}), "reload")
		self.assertEqual(retry_mode("/api/method/frappe.desk.form.save.savedocs", {}), "repeat")
		self.assertEqual(retry_mode("/api/method/run_doc_method", {}), "repeat")


class TestUnlock(unittest.TestCase):
	def test_open_until_the_duration_or_idle_limit(self):
		state = {"since": 1000.0, "seen": 1000.0}
		self.assertEqual(unlocked_until(state, 1100.0, 30, 10), 1600.0)
		self.assertEqual(unlocked_until(state, 1100.0, 30, 0), 2800.0)

	def test_activity_extends_up_to_the_duration(self):
		state = {"since": 1000.0, "seen": 2500.0}
		self.assertEqual(unlocked_until(state, 2600.0, 30, 10), 2800.0)

	def test_expired_or_missing_state_is_locked(self):
		self.assertIsNone(unlocked_until({"since": 1000.0, "seen": 1000.0}, 1601.0, 30, 10))
		self.assertIsNone(unlocked_until({"since": 1000.0, "seen": 1000.0}, 1301.0, 5, 0))
		self.assertIsNone(unlocked_until(None, 1000.0, 30, 10))

	def test_end_reason_is_the_earlier_limit(self):
		self.assertEqual(unlock_end({"since": 1000.0, "seen": 1000.0}, 30, 10), (1600.0, "idle"))
		self.assertEqual(unlock_end({"since": 1000.0, "seen": 2500.0}, 30, 10), (2800.0, "time"))
		self.assertEqual(unlock_end({"since": 1000.0, "seen": 1000.0}, 30, 0), (2800.0, "time"))

	def test_longest_minutes_covers_per_object_durations(self):
		config = {"unlock_minutes": 30, "doctypes": {"Employee": None}, "reports": {"R": 90}, "pages": {}}
		self.assertEqual(longest_minutes(config), 90)
		self.assertEqual(longest_minutes({**config, "reports": {"R": 10}}), 30)

	def test_failures_block_at_the_limit(self):
		self.assertEqual(after_failure(0, 5), (1, False))
		self.assertEqual(after_failure(4, 5), (5, True))
		self.assertEqual(after_failure(None, 5), (1, False))
		self.assertEqual(after_failure(10, 0), (11, False))


BEFORE_SETTINGS = {
	"enabled": 1,
	"unlock_minutes": 30,
	"objects": [{"object_type": "DocType", "object_name": "Employee", "unlock_minutes": 0}],
	"fields": [{"document_type": "Employee", "fieldname": "ctc", "label": "CTC"}],
}


class TestSettingsDelta(unittest.TestCase):
	BEFORE = BEFORE_SETTINGS

	def test_unchanged_settings_give_an_empty_delta(self):
		self.assertEqual(settings_delta(self.BEFORE, self.BEFORE), {})

	def test_changed_values_and_rows(self):
		after = {
			**self.BEFORE,
			"unlock_minutes": 15,
			"objects": [
				{"object_type": "DocType", "object_name": "Employee", "unlock_minutes": 5},
				{"object_type": "Page", "object_name": "payroll", "label": "Payroll"},
			],
			"fields": [],
		}
		self.assertEqual(
			settings_delta(self.BEFORE, after),
			{
				"unlock_minutes": [30, 15],
				"objects_added": [{"object_type": "Page", "object_name": "payroll", "label": "Payroll"}],
				"fields_removed": [{"document_type": "Employee", "fieldname": "ctc", "label": "CTC"}],
				"objects_minutes": [
					{
						"object_type": "DocType",
						"object_name": "Employee",
						"label": None,
						"was": 0,
						"now": 5,
					}
				],
			},
		)

	def test_first_save_lists_everything_as_added(self):
		delta = settings_delta(None, self.BEFORE)
		self.assertEqual(delta["enabled"], [None, 1])
		self.assertEqual(len(delta["objects_added"]), 1)
