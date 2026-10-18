import unittest

import frappe


def group(name, parent="All Customer Groups"):
	return frappe.get_doc(
		{
			"doctype": "Customer Group",
			"customer_group_name": name,
			"parent_customer_group": parent,
			"is_group": 1,
		}
	).insert()


def position(name):
	return frappe.db.get_value("Customer Group", name, ["lft", "rgt"])


def misplaced():
	return frappe.db.sql(
		"""select child.name from `tabCustomer Group` child
		join `tabCustomer Group` parent on parent.name = child.parent_customer_group
		where child.lft <= parent.lft or child.rgt >= parent.rgt or child.lft >= child.rgt""",
		pluck=True,
	)


class TestKeepTreePosition(unittest.TestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_stale_save_keeps_tree(self):
		branch = group("_Test Stale Branch")
		stale = frappe.get_doc("Customer Group", branch.name)
		leaf = group("_Test Stale Leaf", branch.name)

		stale.default_price_list = None
		stale.save()

		lft, rgt = position(branch.name)
		leaf_lft, leaf_rgt = position(leaf.name)
		self.assertTrue(lft < leaf_lft < leaf_rgt < rgt)
		self.assertEqual(misplaced(), [])

	def test_stale_move_keeps_tree(self):
		branch = group("_Test Stale Moved")
		target = group("_Test Stale Target")
		stale = frappe.get_doc("Customer Group", branch.name)
		group("_Test Stale Moved Leaf", branch.name)

		stale.parent_customer_group = target.name
		stale.save()

		target_lft, target_rgt = position(target.name)
		lft, rgt = position(branch.name)
		self.assertTrue(target_lft < lft < rgt < target_rgt)
		self.assertEqual(misplaced(), [])
