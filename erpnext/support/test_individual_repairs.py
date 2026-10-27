"""End-to-end regression tests for individual repair cards, custody and assignment."""

from unittest import TestCase
from unittest.mock import patch

import frappe

from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.support.repair_unit_movement import consume_parts, register
from erpnext.support.repair_units import change_stage, create_units, summary, warehouse_for


class TestIndividualRepairs(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		from frappe.cache_manager import clear_doctype_map

		clear_doctype_map("Assignment Rule", "Repair Unit")
		self.notify = self.enterContext(
			patch("frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification")
		)
		frappe.db.set_single_value("Support Settings", "track_service_level_agreement", 0)
		settings = frappe.get_single("Repair Settings")
		settings.set("warehouses", [{"company": "_Test Company", "warehouse": "Stores - _TC"}])
		settings.save()
		self.item = self.new_item()
		self.contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": frappe.generate_hash(length=10)}
		).insert()
		self.request = self.request_doc()
		self.names = create_units(self.request.name)

	def tearDown(self):
		from frappe.cache_manager import clear_doctype_map

		frappe.set_user("Administrator")
		frappe.db.rollback()
		clear_doctype_map("Assignment Rule", "Repair Unit")
		frappe.local.request_cache.clear()
		if hasattr(frappe.local, "future_sle"):
			frappe.local.future_sle.clear()

	def new_item(self):
		return frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": frappe.generate_hash(length=16),
				"item_group": "Products",
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert()

	def request_doc(self, previous=None):
		return frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": "Individual repair regression",
				"company": "_Test Company",
				"contact": self.contact.name,
				"custom_service_repair": 1,
				"custom_repair_return_address": "Return address",
				"custom_repair_items": [
					{
						"item_code": self.item.name,
						"product_name": "Customer device A",
						"fault_description": "No power",
						"previous_repair": previous,
					}
				]
				if previous
				else [
					{
						"item_code": self.item.name,
						"product_name": "Customer device A",
						"fault_description": "No power",
					},
					{
						"item_code": self.item.name,
						"product_name": "Customer device B",
						"fault_description": "No picture",
					},
				],
			}
		).insert()

	def receive(self, units=None, **kwargs):
		kwargs = {"delivery_type": "Self Pickup", "delivery_details": "Received at service desk", **kwargs}
		return frappe.get_doc(
			"Repair Movement", register(self.request.name, units or self.names, "receive", **kwargs)
		)

	def ready(self, name, outcome="Repaired"):
		unit = frappe.get_doc("Repair Unit", name)
		unit.diagnosis = "Identified defect"
		unit.work_done = "Repaired and tested"
		unit.outcome = outcome
		unit.save()
		change_stage(name, "Ready for Dispatch")

	def test_cards_replace_grouped_order_and_creation_is_idempotent(self):
		self.assertEqual(len(self.names), 2)
		self.assertEqual(create_units(self.request.name), self.names)
		self.assertFalse(frappe.db.exists("Repair Order", {"issue": self.request.name}))
		for name in self.names:
			unit = frappe.get_doc("Repair Unit", name)
			self.assertEqual(unit.issue, self.request.name)
			self.assertEqual(unit.item_code, self.item.name)
			self.assertEqual(unit.status, "Awaiting Receipt")
			self.assertFalse(unit.received_on)

	def test_work_is_individual_costed_and_append_only(self):
		self.receive()
		unit = frappe.get_doc("Repair Unit", self.names[0])
		unit.append(
			"work_log",
			{"notes": "Replaced connector", "labor_cost": 35, "cost_note": "Labor", "performed_by": "Guest"},
		)
		unit.save()
		self.assertEqual(unit.total_cost, 35)
		self.assertEqual(unit.work_log[0].performed_by, "Administrator")
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[1], "total_cost"), 0)
		unit.work_log[0].notes = "Overwrite history"
		with self.assertRaises(frappe.ValidationError):
			unit.save()

	def test_work_and_forged_status_are_blocked_before_receipt(self):
		unit = frappe.get_doc("Repair Unit", self.names[0])
		unit.diagnosis = "Premature work"
		with self.assertRaises(frappe.ValidationError):
			unit.save()
		unit.reload()
		unit.status = "Delivered"
		with self.assertRaises(frappe.ValidationError):
			unit.save()

	def test_browser_json_saves_work_and_preserves_protected_dates(self):
		self.receive(units=[self.names[0]])
		unit = frappe.get_doc("Repair Unit", self.names[0])
		unit.append("work_log", {"notes": "Initial inspection"})
		unit.save()
		original_date = unit.work_log[0].performed_on
		browser = frappe.get_doc(frappe.parse_json(unit.as_json()))
		browser.diagnosis = "Fault confirmed from form"
		browser.repair_user = ""
		browser.append("work_log", {"notes": "Follow-up inspection"})
		browser.save()
		self.assertEqual(browser.diagnosis, "Fault confirmed from form")
		self.assertEqual(len(browser.work_log), 2)
		self.assertEqual(str(browser.work_log[0].performed_on), str(original_date))
		browser = frappe.get_doc(frappe.parse_json(browser.as_json()))
		browser.work_log[0].performed_on = "2000-01-01 00:00:00"
		with self.assertRaisesRegex(frappe.ValidationError, "append-only"):
			browser.save()
		browser = frappe.get_doc(frappe.parse_json(unit.reload().as_json()))
		browser.received_on = None
		with self.assertRaisesRegex(frappe.ValidationError, "repair actions"):
			browser.save()

	def test_receipt_serials_and_cancellation_do_not_touch_stock(self):
		frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 0)
		entry = self.receive(
			units=list(reversed(self.names)), serials={self.names[0]: "A", self.names[1]: "B"}
		)
		self.assertEqual(
			[row["name"] for row in summary(frappe.get_doc("Repair Unit", self.names[0]))["movements"]],
			[entry.name],
		)
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "factory_serial"), "A")
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[1], "warehouse"), "Stores - _TC")
		self.assertFalse(frappe.db.exists("Bin", {"item_code": self.item.name}))
		self.assertFalse(frappe.db.exists("Serial No", {"name": ["in", self.names]}))
		with self.assertRaises(frappe.ValidationError):
			register(self.request.name, self.names, "transfer", warehouse="Finished Goods - _TC")
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "warehouse"), "Stores - _TC")
		entry.cancel()
		self.assertFalse(frappe.db.get_value("Repair Unit", self.names[0], "received_on"))
		self.assertFalse(frappe.db.get_value("Repair Unit", self.names[0], "factory_serial"))

	def test_partial_dispatch_and_repeat_repair_create_new_card(self):
		self.receive()
		self.ready(self.names[0])
		register(
			self.request.name, [self.names[0]], "dispatch", waybill="PARTIAL-TTN", delivery_type="Nova Poshta"
		)
		change_stage(self.names[0], "Delivered")
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[1], "status"), "Received")
		self.assertEqual(self.request.reload().custom_repair_shipments[0].waybill, "PARTIAL-TTN")
		repeat = self.request_doc(self.names[0])
		new_name = create_units(repeat.name)[0]
		self.assertNotEqual(new_name, self.names[0])
		new = frappe.get_doc("Repair Unit", new_name)
		self.assertEqual(new.previous_repair, self.names[0])
		self.assertEqual(new.issue, repeat.name)
		self.assertEqual(new.total_cost, 0)
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "status"), "Delivered")

	def test_real_parts_use_stock_documents_and_cost_one_card(self):
		self.receive()
		change_stage(self.names[0], "In Repair")
		part = self.new_item()
		make_stock_entry(item_code=part.name, qty=2, rate=10, target="Stores - _TC")
		entry = frappe.get_doc(
			"Stock Entry",
			consume_parts(self.names[0], [{"item_code": part.name, "qty": 2, "warehouse": "Stores - _TC"}]),
		)
		user = self.user()
		frappe.db.set_value("Stock Entry", entry.name, "owner", user.name, update_modified=False)
		entry.reload()
		entry.custom_repair_data = '{"posted_by": "Guest"}'
		entry.submit()
		history = summary(frappe.get_doc("Repair Unit", self.names[0]))["consumed_parts"]
		self.assertEqual(len(history), 1)
		self.assertEqual(history[0]["stock_entry"], entry.name)
		self.assertEqual(history[0]["item_code"], part.name)
		self.assertEqual(history[0]["posted_by"], "Administrator")
		self.assertEqual(history[0]["qty"], 2)
		self.assertEqual(history[0]["amount"], 20)
		self.assertEqual(history[0]["rate"], 10)
		self.assertEqual(summary(frappe.get_doc("Repair Unit", self.names[1]))["consumed_parts"], [])
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "parts_cost"), 20)
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[1], "parts_cost"), 0)
		entry.cancel()
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "parts_cost"), 0)
		self.assertEqual(
			summary(frappe.get_doc("Repair Unit", self.names[0]))["consumed_parts"][0]["docstatus"], 2
		)
		frappe.set_user(user.name)
		try:
			history = summary(frappe.get_doc("Repair Unit", self.names[0]))["consumed_parts"]
			self.assertEqual(history[0]["item_code"], part.name)
			self.assertFalse(history[0]["can_open"])
		finally:
			frappe.set_user("Administrator")

	def test_company_warehouse_map_validates_company_and_duplicates(self):
		settings = frappe.get_single("Repair Settings")
		other = frappe.db.get_value(
			"Warehouse", {"company": "_Test Company 1", "is_group": 0, "disabled": 0}, "name"
		)
		self.assertTrue(other)
		settings.append("warehouses", {"company": "_Test Company 1", "warehouse": other})
		settings.save()
		self.assertEqual(warehouse_for("_Test Company"), "Stores - _TC")
		self.assertEqual(warehouse_for("_Test Company 1"), other)
		with self.assertRaises(frappe.ValidationError):
			register(
				self.request.name,
				self.names,
				"receive",
				warehouse=other,
				delivery_type="Self Pickup",
				delivery_details="Received at service desk",
			)
		settings.warehouses[1].warehouse = "Stores - _TC"
		with self.assertRaises(frappe.ValidationError):
			settings.save()
		settings.reload()
		settings.append("warehouses", {"company": "_Test Company", "warehouse": "Finished Goods - _TC"})
		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def user(self, role=None):
		roles = [{"role": "Repair Technician"}]
		if role:
			roles.append({"role": role})
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": f"repair-{frappe.generate_hash(length=12)}@example.invalid",
				"first_name": "Repair test",
				"enabled": 1,
				"send_welcome_email": 0,
				"roles": roles,
			}
		).insert()

	def test_role_assignment_runs_on_receipt_not_creation(self):
		role = frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": f"Repair pool {frappe.generate_hash(length=8)}",
				"desk_access": 1,
			}
		).insert()
		user = self.user(role.name)
		rule = frappe.get_doc(
			{
				"doctype": "Assignment Rule",
				"name": f"Repair rule {frappe.generate_hash(length=10)}",
				"document_type": "Repair Unit",
				"custom_repair_assignee_role": role.name,
				"rule": "Round Robin",
				"priority": 9999,
				"description": "Repair {{ name }}",
				"assign_condition": "status == 'Received'",
				"assignment_days": [
					{"day": day}
					for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
				],
			}
		).insert()
		self.assertEqual(rule.users[0].user, user.name)
		self.assertFalse(
			frappe.db.exists(
				"ToDo", {"reference_type": "Repair Unit", "reference_name": self.names[0], "status": "Open"}
			)
		)
		entry = self.receive(units=[self.names[0]])
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "repair_user"), user.name)
		self.assertTrue(
			frappe.db.exists(
				"ToDo",
				{
					"reference_type": "Repair Unit",
					"reference_name": self.names[0],
					"allocated_to": user.name,
					"status": "Open",
				},
			)
		)
		self.assertFalse(
			frappe.db.exists(
				"ToDo", {"reference_type": "Repair Unit", "reference_name": self.names[1], "status": "Open"}
			)
		)
		entry.cancel()
		self.assertFalse(
			frappe.db.exists(
				"ToDo", {"reference_type": "Repair Unit", "reference_name": self.names[0], "status": "Open"}
			)
		)

	def test_technician_cannot_perform_support_logistics(self):
		self.receive()
		user = self.user()
		frappe.set_user(user.name)
		try:
			change_stage(self.names[0], "In Repair")
			unit = frappe.get_doc("Repair Unit", self.names[0])
			unit.diagnosis = "Individual diagnosis"
			unit.save()
			with self.assertRaises(frappe.PermissionError):
				register(self.request.name, self.names, "dispatch", waybill="NO-ACCESS")
			with self.assertRaises(frappe.PermissionError):
				change_stage(self.names[0], "Delivered")
		finally:
			frappe.set_user("Administrator")

	def test_priority_follows_source_request(self):
		priority = frappe.get_doc(
			{"doctype": "Issue Priority", "name": f"Priority {frappe.generate_hash(length=8)}"}
		).insert()
		self.request.reload()
		self.request.priority = priority.name
		self.request.save()
		self.assertEqual(
			[frappe.db.get_value("Repair Unit", name, "priority") for name in self.names],
			[priority.name, priority.name],
		)

	def test_delivery_types_are_recorded_for_receipt_and_dispatch(self):
		for kind in ("Nova Poshta", "Ukrposhta", "Taxi", "Self Pickup", "Other"):
			with self.subTest(delivery_type=kind):
				request = self.request_doc()
				name = create_units(request.name)[0]
				postal = kind in {"Nova Poshta", "Ukrposhta"}
				values = {
					"delivery_type": kind,
					"waybill": "POSTAL-TTN" if postal else "unused",
					"delivery_details": "unused" if postal else "Driver or recipient details",
				}
				receipt = frappe.get_doc(
					"Repair Movement", register(request.name, [name], "receive", **values)
				)
				request.reload()
				self.assertEqual(request.custom_repair_delivery_type, kind)
				self.assertEqual(receipt.delivery_type, kind)
				if postal:
					self.assertEqual(request.custom_repair_waybill, "POSTAL-TTN")
					self.assertFalse(request.custom_repair_delivery_details)
				else:
					self.assertFalse(request.custom_repair_waybill)
					self.assertEqual(request.custom_repair_delivery_details, "Driver or recipient details")
				self.ready(name)
				register(request.name, [name], "dispatch", **values)
				shipment = request.reload().custom_repair_shipments[0]
				self.assertEqual(shipment.delivery_type, kind)
				self.assertEqual(
					shipment.waybill if postal else shipment.delivery_details,
					"POSTAL-TTN" if postal else "Driver or recipient details",
				)
				self.assertEqual(request.custom_repair_items[0].repair_outcome, "Repaired")

	def test_delivery_validation_requires_the_matching_details(self):
		for values in (
			{},
			{"delivery_type": "Nova Poshta"},
			{"delivery_type": "Ukrposhta", "delivery_details": "Not a TTN"},
			{"delivery_type": "Taxi", "waybill": "Not details"},
			{"delivery_type": "Other"},
			{"delivery_type": "Unknown"},
		):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				register(self.request.name, self.names, "receive", **values)
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "status"), "Awaiting Receipt")

	def test_disposal_requires_consent_and_result_but_attachment_is_optional(self):
		self.receive()
		self.ready(self.names[0], "Not Repairable")
		self.ready(self.names[1])
		with self.assertRaisesRegex(frappe.ValidationError, "agreed"):
			register(self.request.name, [self.names[0]], "dispose")
		with self.assertRaisesRegex(frappe.ValidationError, "Not Repairable"):
			register(self.request.name, [self.names[1]], "dispose", disposal_approved=1)
		with self.assertRaisesRegex(frappe.ValidationError, "saved disposal"):
			register(
				self.request.name,
				[self.names[0]],
				"dispose",
				disposal_approved=1,
				approval="/files/missing.pdf",
			)
		name = register(self.request.name, [self.names[0]], "dispose", disposal_approved=1)
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "status"), "Disposed")
		shipment = self.request.reload().custom_repair_shipments[0]
		self.assertEqual(shipment.disposal_approved, 1)
		self.assertFalse(shipment.approval)
		frappe.get_doc("Repair Movement", name).cancel()
		self.assertEqual(frappe.db.get_value("Repair Unit", self.names[0], "status"), "Ready for Dispatch")
		self.assertTrue(self.request.reload().custom_repair_shipments[0].cancelled)

	def test_legacy_cards_without_source_links_migrate_once(self):
		from erpnext.support.repair_units import internal_action
		from erpnext.support.repair_units_setup import execute

		request = self.request_doc()
		legacy = frappe.get_doc(
			{
				"doctype": "Repair Order",
				"issue": request.name,
				"company": request.company,
				"currency": "INR",
				"support_user": "Administrator",
			}
		)
		with internal_action():
			for source in request.custom_repair_items:
				unit = frappe.get_doc(
					{
						"doctype": "Repair Unit",
						"company": request.company,
						"item_code": source.item_code,
						"product_name": source.product_name,
					}
				).insert(ignore_permissions=True)
				legacy.append(
					"items",
					{
						"repair_unit": unit.name,
						"product_name": source.product_name,
						"fault_description": source.fault_description,
						"status": "Received",
						"warehouse": "Stores - _TC",
						"work_done": "Existing work",
						"labor_cost": 15,
						"cost_note": "Previous labor",
					},
				)
			legacy.flags.repair_action = True
			legacy.insert()
		execute()
		request.reload()
		for source in request.custom_repair_items:
			unit = frappe.get_doc("Repair Unit", source.repair_unit)
			self.assertEqual(unit.issue, request.name)
			self.assertEqual(unit.work_done, "Existing work")
			self.assertEqual(unit.labor_cost, 15)
			self.assertEqual(len(unit.work_log), 1)
			self.assertEqual(summary(unit)["legacy_order"], legacy.name)
		unit.append("work_log", {"notes": "New work", "labor_cost": 10, "cost_note": "More labor"})
		unit.save()
		execute()
		unit.reload()
		self.assertEqual(unit.labor_cost, 25)
		self.assertEqual(len(unit.work_log), 2)
