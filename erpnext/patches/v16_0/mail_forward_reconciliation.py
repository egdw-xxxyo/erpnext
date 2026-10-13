import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now_datetime

from erpnext.correspondence.mail_forward import PROCESSED_FIELD, SETTINGS


def execute():
	create_custom_fields(
		{
			"Communication": [
				{
					"fieldname": PROCESSED_FIELD,
					"fieldtype": "Check",
					"label": "Mail Forward Processed",
					"insert_after": "email_account",
					"default": "0",
					"hidden": 1,
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				}
			]
		},
		ignore_validate=True,
	)
	if frappe.db.get_single_value(SETTINGS, "enabled") and not frappe.db.get_single_value(
		SETTINGS, "enabled_since"
	):
		frappe.db.set_single_value(SETTINGS, "enabled_since", now_datetime(), update_modified=False)
