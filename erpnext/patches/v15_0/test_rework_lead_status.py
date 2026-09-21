import unittest
from unittest.mock import patch

import frappe
from frappe.core.doctype.doctype.doctype import validate_fields_for_doctype

from erpnext.patches.v15_0 import rework_lead_status


class StopBeforeDataMigration(Exception):
	pass


class TestLeadStatusMigration(unittest.TestCase):
	def test_invalid_default_is_fixed_before_custom_field_validation(self):
		user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.savepoint("lead_status_metadata_test")
		try:
			frappe.make_property_setter(
				{
					"doctype": "Lead",
					"fieldname": "status",
					"property": "default",
					"value": "Lead",
					"property_type": "Select",
				},
				validate_fields_for_doctype=False,
			)
			with self.assertRaises(frappe.ValidationError):
				validate_fields_for_doctype("Lead")

			def validate_before_creating_fields():
				# Custom Field.on_update performs this same full-schema validation.
				validate_fields_for_doctype("Lead")
				self.assertEqual(frappe.get_meta("Lead").get_field("status").default, "New Request")
				raise StopBeforeDataMigration

			# Avoid schema DDL and Lead data migration; exercise the real Property Setters.
			with (
				patch.object(frappe, "reload_doctype"),
				patch.object(
					rework_lead_status,
					"ensure_lead_custom_fields",
					side_effect=validate_before_creating_fields,
				),
			):
				for _attempt in range(2):
					with self.assertRaises(StopBeforeDataMigration):
						rework_lead_status.execute()
		finally:
			frappe.db.rollback(save_point="lead_status_metadata_test")
			frappe.clear_cache(doctype="Lead")
			frappe.set_user(user)
