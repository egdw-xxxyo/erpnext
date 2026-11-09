"""Quantity conservation, serial restrictions and result-specific repair logistics."""

from unittest import TestCase

import frappe

from erpnext.support.repair_unit_movement import register
from erpnext.support.repair_units import change_stage, create_units
from erpnext.support.test_individual_repairs import TestIndividualRepairs


class TestRepairBatches(TestCase):
	setUp = TestIndividualRepairs.setUp
	tearDown = TestIndividualRepairs.tearDown
	new_item = TestIndividualRepairs.new_item
	request_doc = TestIndividualRepairs.request_doc
	receive = TestIndividualRepairs.receive

	def batch(self):
		self.request = self.request_doc()
		row = self.request.custom_repair_items[0]
		row.qty = 20
		row.accessories = "Same accessories"
		self.request.set("custom_repair_items", [row])
		self.request.save()
		self.names = create_units(self.request.name)
		receipt = self.receive()
		change_stage(self.names[0], "In Repair")
		return receipt, frappe.get_doc("Repair Unit", self.names[0])

	def test_results_split_rows_and_keep_receipt_quantity(self):
		receipt, unit = self.batch()
		unit.work_done = "Checked all 20 items"
		unit.repaired_qty = 10
		unit.no_fault_qty = 5
		unit.not_repairable_qty = 5
		unit.append(
			"work_log", {"notes": "Shared batch diagnosis", "labor_cost": 100, "cost_note": "Batch cost"}
		)
		unit.save()
		change_stage(unit.name, "Ready for Dispatch")
		rows = self.request.reload().custom_repair_items
		self.assertEqual(len(rows), 3)
		self.assertEqual(
			{row.repair_outcome: row.qty for row in rows},
			{
				"Repaired": 10,
				"No Fault Found": 5,
				"Not Repairable": 5,
			},
		)
		self.assertTrue(all(row.accessories == "Same accessories" for row in rows))
		self.assertEqual(receipt.reload().items[0].qty, 20)
		cards = [frappe.get_doc("Repair Unit", row.repair_unit) for row in rows]
		self.assertEqual(sum(card.qty for card in cards), 20)
		self.assertEqual(sum(card.total_cost for card in cards), 100)
		self.assertTrue(all(card.repair_user == "Administrator" for card in cards))
		self.assertTrue(all(card.split_from == unit.name for card in cards[1:]))
		change_stage(unit.name, "Ready for Dispatch")
		self.assertEqual(len(self.request.reload().custom_repair_items), 3)
		with self.assertRaises(frappe.ValidationError):
			receipt.cancel()

	def test_reject_overallocation_and_incomplete_final_result(self):
		_, unit = self.batch()
		unit.repaired_qty = 21
		with self.assertRaisesRegex(frappe.ValidationError, "cannot exceed"):
			unit.save()
		unit.reload()
		unit.repaired_qty = 10
		unit.work_done = "Ten repaired so far"
		unit.save()
		with self.assertRaisesRegex(frappe.ValidationError, "entire repair quantity"):
			change_stage(unit.name, "Ready for Dispatch")
		self.assertEqual(len(self.request.reload().custom_repair_items), 1)
		unit.reload()
		unit.not_repairable_qty = -1
		with self.assertRaises(frappe.ValidationError):
			unit.save()

	def test_independent_dispatch_disposal_and_closure(self):
		_, unit = self.batch()
		unit.work_done = "Repaired 15, five cannot be repaired"
		unit.repaired_qty = 15
		unit.not_repairable_qty = 5
		unit.save()
		change_stage(unit.name, "Ready for Dispatch")
		rows = self.request.reload().custom_repair_items
		unrepairable = next(row.repair_unit for row in rows if row.repair_outcome == "Not Repairable")
		with self.assertRaises(frappe.ValidationError):
			register(self.request.name, [unit.name], "dispose", disposal_approved=1)
		register(self.request.name, [unrepairable], "dispose", disposal_approved=1)
		dispatch = register(
			self.request.name,
			[unit.name],
			"dispatch",
			delivery_type="Self Pickup",
			delivery_details="Returned",
		)
		self.assertEqual(frappe.db.get_value("Repair Movement Item", {"parent": dispatch}, "qty"), 15)
		self.assertNotEqual(self.request.reload().status, "Closed")
		change_stage(unit.name, "Delivered")
		self.assertEqual(self.request.reload().status, "Closed")
		self.assertEqual(sorted(row.qty for row in self.request.custom_repair_shipments), [5, 15])

	def test_serial_restrictions(self):
		with self.assertRaisesRegex(frappe.ValidationError, "only available"):
			self.receive(serials={self.names[0]: "NOT-ALLOWED"})
		self.item.has_serial_no = 1
		self.item.save()
		request = self.request_doc()
		request.custom_repair_items[0].qty = 20
		with self.assertRaisesRegex(frappe.ValidationError, "quantity 1"):
			request.save()
		request.reload()
		names = create_units(request.name)
		movement = register(
			request.name,
			names,
			"receive",
			delivery_type="Self Pickup",
			delivery_details="Test",
			serials={names[0]: "SERIAL-1"},
		)
		self.assertEqual(frappe.get_doc("Repair Movement", movement).items[0].factory_serial, "SERIAL-1")
