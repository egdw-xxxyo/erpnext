import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Work Order": [
				{
					"fieldname": "serial_nos_html",
					"fieldtype": "HTML",
					"label": "Серійні номери",
					"insert_after": "has_serial_no",
					"depends_on": "has_serial_no",
				},
			]
		}
	)
