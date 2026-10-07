"""The Scanner Overview page became Device Overview (it now covers OTDR benches too).

Migrate syncs the new page from its folder but never removes a standard Page whose folder
is gone, so the old record would stay in the page list and in role permissions.
"""

import frappe


def execute():
	if frappe.db.exists("Page", "scanner-overview"):
		frappe.delete_doc("Page", "scanner-overview", force=True, ignore_missing=True)
