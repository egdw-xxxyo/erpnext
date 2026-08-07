"""Remove the desk-era Custom Field `Lead.custom_військова_частина`.

The Military Unit of a Lead is now the standard `military_unit` field, mirrored from the
linked Prospect / Customer by `Lead.set_military_unit`. The old free-standing Custom Field
only exists on sites where it was created through the desk (dev); prod never had it, so
every step is guarded.
"""

import frappe

LEGACY_FIELDNAME = "custom_військова_частина"


def execute():
	custom_field = frappe.db.exists("Custom Field", {"dt": "Lead", "fieldname": LEGACY_FIELDNAME})
	if not custom_field:
		return

	if frappe.db.has_column("Lead", LEGACY_FIELDNAME) and frappe.db.has_column("Lead", "military_unit"):
		_carry_over_values()

	frappe.delete_doc("Custom Field", custom_field, ignore_permissions=True, force=True)
	frappe.db.commit()
	frappe.clear_cache(doctype="Lead")


def _carry_over_values():
	"""Keep values that point at a real Military Unit and would otherwise be lost.

	`military_unit` is normally derived from the organization, so only Leads that have no
	value yet are touched — a derived value always wins over the legacy free text.
	"""
	rows = frappe.db.sql(
		"""
		SELECT name, `custom_військова_частина` AS legacy_value
		FROM `tabLead`
		WHERE COALESCE(`custom_військова_частина`, '') != ''
			AND COALESCE(military_unit, '') = ''
		""",
		as_dict=True,
	)

	for row in rows:
		if frappe.db.exists("Military Unit", row.legacy_value):
			frappe.db.set_value("Lead", row.name, "military_unit", row.legacy_value, update_modified=False)
