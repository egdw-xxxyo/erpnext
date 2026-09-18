# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Move what the register keeps of a codification onto the modification it describes.

`NATO Codification` is gone from the module: the procedure around the code — its status,
its dates, who was responsible — is not something the register tracks, and keeping a
second card per modification only to hold one code cost a doctype, a set of permission
rules and a panel. What is worth keeping is the code itself, the date it was issued, and
the documents it was issued against, and all three belong on the modification.

The prototype's rows are carried across rather than retyped. Nothing is written over: a
modification that already has a code, or already has a package, is left exactly as it is,
so the patch can run twice and on a site that never saw the prototype it does nothing at
all. The codification rows themselves are not deleted — the table stays where it is, with
its data, for whoever wants to look at what the procedure recorded.

The source is read with SQL rather than through the ORM on purpose: the DocType record
behind those tables is on its way out (migrate drops the entry of any doctype whose code is
gone, leaving the table), so a query that needs its meta would work during the migration
that removes it and fail on every run afterwards.
"""

import frappe

SOURCE = "NATO Codification"
SOURCE_PACKAGE = "NATO Codification Document"
TARGET = "Product Modification"
TARGET_PACKAGE = "Product Modification Document"
DROPPED_NUMBER_CARD = "Codification in Progress"


def execute():
	drop_number_card()

	if not (frappe.db.table_exists(SOURCE) and frappe.db.table_exists(TARGET)):
		return

	for row in frappe.db.sql(  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
		f"""select name, product_modification, nsn_code, end_date
		from `tab{SOURCE}` where ifnull(product_modification, '') != ''""",
		as_dict=True,
	):
		modification = frappe.db.get_value(
			TARGET, row.product_modification, ["name", "nsn_code"], as_dict=True
		)
		if not modification:
			continue

		carry_code(modification, row)
		carry_package(modification.name, row.name)

	frappe.db.commit()


def drop_number_card():
	"""The workspace counted codifications in progress; there is no such record any more."""
	if frappe.db.exists("Number Card", DROPPED_NUMBER_CARD):
		frappe.delete_doc("Number Card", DROPPED_NUMBER_CARD, ignore_permissions=True, force=True)


def carry_code(modification, codification):
	if modification.nsn_code or not codification.nsn_code:
		return

	frappe.db.set_value(
		TARGET,
		modification.name,
		{"nsn_code": codification.nsn_code, "nsn_date": codification.end_date},
		update_modified=False,
	)


def carry_package(modification, codification):
	if not frappe.db.table_exists(SOURCE_PACKAGE):
		return

	if frappe.db.exists(TARGET_PACKAGE, {"parenttype": TARGET, "parent": modification}):
		return

	rows = frappe.db.sql(  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
		f"""select document_type, technical_document, document_revision, note, idx
		from `tab{SOURCE_PACKAGE}` where parenttype = %s and parent = %s order by idx""",
		(SOURCE, codification),
		as_dict=True,
	)

	for row in rows:
		package_row = frappe.get_doc(
			{
				"doctype": TARGET_PACKAGE,
				"parenttype": TARGET,
				"parentfield": "documents",
				"parent": modification,
				**row,
			}
		)
		package_row.db_insert()
