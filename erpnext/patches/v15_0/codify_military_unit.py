"""Take ownership of the `Military Unit` DocType in code.

It was originally created through the desk UI (``custom = 1``), so it lived only in the
site database and would never reach another environment through the Docker image. This
patch flips it to a code-owned DocType and drops the auto-generated Cyrillic section
break fieldname, which `military_unit.json` replaces with `military_unit_section`.
"""

import frappe

DOCTYPE = "Military Unit"
LEGACY_SECTION_FIELDNAME = "військова_частина_section"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		frappe.reload_doc("crm", "doctype", "military_unit", force=True)
		return

	frappe.db.set_value("DocType", DOCTYPE, "custom", 0, update_modified=False)
	frappe.db.delete("DocField", {"parent": DOCTYPE, "fieldname": LEGACY_SECTION_FIELDNAME})

	# The desk-created version stored Ukrainian labels directly; the code version keeps
	# English labels and translates them through erpnext/translations/uk.csv. Drop any
	# Property Setter that would otherwise pin the old labels or options.
	stale = frappe.get_all(
		"Property Setter",
		filters={"doc_type": DOCTYPE},
		pluck="name",
	)
	for name in stale:
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	frappe.reload_doc("crm", "doctype", "military_unit", force=True)
	frappe.db.commit()
	frappe.clear_cache(doctype=DOCTYPE)
