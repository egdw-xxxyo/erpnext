import json
import unittest

import frappe

from erpnext.patches.v15_0 import add_eskd_workspace_card as patch


class TestESKDWorkspaceMigration(unittest.TestCase):
	def test_missing_chart_is_preserved_and_card_is_added_once(self):
		user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.savepoint("eskd_workspace_test")
		try:
			workspace = frappe.get_doc("Workspace", "Stock")
			workspace.set("links", [])
			workspace.content = "[]"
			missing_chart = "_Test Chart Synced After Patches"
			self.assertFalse(frappe.db.exists("Dashboard Chart", missing_chart))
			workspace.set("charts", [{"chart_name": missing_chart, "label": missing_chart}])
			workspace.flags.ignore_links = True
			workspace.save(ignore_permissions=True)

			# Reproduce the state between model sync and dashboard sync in migrate.
			with self.assertRaises(frappe.LinkValidationError):
				frappe.get_doc("Workspace", "Stock").save(ignore_permissions=True)

			patch.execute()
			patch.execute()
			workspace = frappe.get_doc("Workspace", "Stock")
			self.assertEqual(workspace.charts[0].chart_name, missing_chart)
			self.assertEqual(
				sum(row.type == "Card Break" and row.label == patch.CARD for row in workspace.links), 1
			)
			self.assertEqual(len(workspace.links), 1 + len(patch.CARD_LINKS))
			self.assertEqual(sum(block["id"] == patch.BLOCK_ID for block in json.loads(workspace.content)), 1)
		finally:
			frappe.db.rollback(save_point="eskd_workspace_test")
			frappe.clear_cache(doctype="Workspace")
			frappe.set_user(user)
