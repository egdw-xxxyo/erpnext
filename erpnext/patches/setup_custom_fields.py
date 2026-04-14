"""Idempotent setup script for custom fields and workflows. Safe to re-run on every deploy.

Run via: docker compose exec -T backend bench --site frontend execute erpnext.patches.setup_custom_fields.execute
Or via bench console and calling execute() manually.
"""
import frappe


def execute():
	create_workflow_states()
	create_workflow_actions()
	create_workflow()
	create_custom_fields_on_item()
	create_item_specification_tab()
	create_custom_fields_on_pr_item()
	create_custom_field_on_qi()
	create_custom_fields_on_work_order()
	create_label_templates_on_employee()
	create_label_templates_on_workplace()
	frappe.db.commit()
	print("Setup complete: PR workflow, custom fields on Item, PR Item, Quality Inspection, Work Order, Employee, and Workplace")


def create_workflow_states():
	states = [
		{"workflow_state_name": "Чернетка", "style": "Primary"},
		{"workflow_state_name": "На перевірці", "style": "Warning"},
		{"workflow_state_name": "На затвердженні", "style": "Info"},
		{"workflow_state_name": "Проведено", "style": "Success"},
	]
	for s in states:
		if not frappe.db.exists("Workflow State", s["workflow_state_name"]):
			doc = frappe.get_doc({
				"doctype": "Workflow State",
				"workflow_state_name": s["workflow_state_name"],
				"style": s["style"],
			})
			doc.insert(ignore_permissions=True)
			print(f"  Created Workflow State: {s['workflow_state_name']}")
		else:
			print(f"  Workflow State exists: {s['workflow_state_name']}")


def create_workflow_actions():
	actions = [
		"На перевірку",
		"Якість підтверджено",
		"Повернути",
		"Провести",
		"Повернути на перевірку",
	]
	for action_name in actions:
		if not frappe.db.exists("Workflow Action Master", action_name):
			doc = frappe.get_doc({
				"doctype": "Workflow Action Master",
				"workflow_action_name": action_name,
			})
			doc.insert(ignore_permissions=True)
			print(f"  Created Workflow Action: {action_name}")
		else:
			print(f"  Workflow Action exists: {action_name}")


def create_workflow():
	workflow_name = "Purchase Receipt QC Workflow"
	if frappe.db.exists("Workflow", workflow_name):
		print(f"  Workflow exists: {workflow_name}")
		return

	doc = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": workflow_name,
		"document_type": "Purchase Receipt",
		"is_active": 1,
		"override_status": 0,
		"send_email_alert": 0,
		"states": [
			{
				"state": "Чернетка",
				"doc_status": "0",
				"allow_edit": "Stock User",
				"is_optional_state": 0,
			},
			{
				"state": "На перевірці",
				"doc_status": "0",
				"allow_edit": "Quality Manager",
				"is_optional_state": 0,
			},
			{
				"state": "На затвердженні",
				"doc_status": "0",
				"allow_edit": "Accounts User",
				"is_optional_state": 0,
			},
			{
				"state": "Проведено",
				"doc_status": "1",
				"allow_edit": "Accounts User",
				"is_optional_state": 0,
			},
		],
		"transitions": [
			{
				"state": "Чернетка",
				"action": "На перевірку",
				"next_state": "На перевірці",
				"allowed": "Stock User",
				"allow_self_approval": 1,
			},
			{
				"state": "На перевірці",
				"action": "Якість підтверджено",
				"next_state": "На затвердженні",
				"allowed": "Quality Manager",
				"allow_self_approval": 1,
			},
			{
				"state": "На перевірці",
				"action": "Повернути",
				"next_state": "Чернетка",
				"allowed": "Quality Manager",
				"allow_self_approval": 1,
			},
			{
				"state": "На затвердженні",
				"action": "Провести",
				"next_state": "Проведено",
				"allowed": "Accounts User",
				"allow_self_approval": 1,
			},
			{
				"state": "На затвердженні",
				"action": "Повернути на перевірку",
				"next_state": "На перевірці",
				"allowed": "Accounts User",
				"allow_self_approval": 1,
			},
		],
	})
	doc.insert(ignore_permissions=True)
	print(f"  Created Workflow: {workflow_name}")


def create_custom_fields_on_item():
	# Remove old fields from previous iterations
	for old_field in ["battery_specs_section", "battery_capacity", "battery_voltage", "cell_type", "item_qc_profile", "item_specification", "label_template", "requires_incoming_qc"]:
		old_cf = frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": old_field})
		if old_cf:
			frappe.delete_doc("Custom Field", old_cf, force=True)
			print(f"  Removed old Custom Field: Item.{old_field}")


def create_item_specification_tab():
	fields = [
		{
			"dt": "Item",
			"fieldname": "specification_tab",
			"fieldtype": "Tab Break",
			"label": "Specification",
			"insert_after": "default_item_manufacturer",
		},
		{
			"dt": "Item",
			"fieldname": "item_spec_parameters",
			"fieldtype": "Table",
			"label": "Specification Parameters",
			"options": "Item Specification Parameter",
			"insert_after": "specification_tab",
		},
		{
			"dt": "Item",
			"fieldname": "label_templates",
			"fieldtype": "Table",
			"label": "Label Templates",
			"options": "Item Label Template",
			"insert_after": "item_spec_parameters",
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_pr_item():
	fields = [
		{
			"dt": "Purchase Receipt Item",
			"fieldname": "accounting_item_name",
			"fieldtype": "Data",
			"label": "Accounting Item Name",
			"insert_after": "item_name",
			"description": "Internal accounting nomenclature (filled by accounting)",
			"depends_on": "eval:cur_frm && ['На затвердженні','Проведено'].includes(cur_frm.doc.workflow_state)",
		},
		{
			"dt": "Purchase Receipt Item",
			"fieldname": "logistics_cost",
			"fieldtype": "Currency",
			"label": "Logistics Cost",
			"insert_after": "amount",
			"description": "Per-item logistics/shipping cost (filled by accounting)",
			"depends_on": "eval:cur_frm && ['На затвердженні','Проведено'].includes(cur_frm.doc.workflow_state)",
		},
	]
	_create_custom_fields(fields)


def create_custom_field_on_qi():
	fields = [
		{
			"dt": "Quality Inspection",
			"fieldname": "serial_inspections",
			"fieldtype": "Table",
			"label": "Serial Inspections",
			"options": "QI Serial Entry",
			"insert_after": "readings",
			"description": "Per-serial-number pass/fail inspection results",
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_work_order():
	fields = [
		{
			"dt": "Work Order",
			"fieldname": "serial_nos_html",
			"fieldtype": "HTML",
			"label": "Серійні номери",
			"insert_after": "has_serial_no",
			"depends_on": "has_serial_no",
		},
	]
	_create_custom_fields(fields)


def create_label_templates_on_employee():
	fields = [
		{
			"dt": "Employee",
			"fieldname": "label_templates",
			"fieldtype": "Table",
			"label": "Label Templates",
			"options": "Item Label Template",
			"insert_after": "attendance_device_id",
		},
	]
	_create_custom_fields(fields)


def create_label_templates_on_workplace():
	fields = [
		{
			"dt": "Workplace",
			"fieldname": "label_templates",
			"fieldtype": "Table",
			"label": "Label Templates",
			"options": "Item Label Template",
			"insert_after": "barcode",
		},
	]
	_create_custom_fields(fields)


def _create_custom_fields(fields):
	for f in fields:
		existing = frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]})
		if existing:
			print(f"  Custom Field exists: {f['dt']}.{f['fieldname']}")
			continue

		doc = frappe.get_doc({
			"doctype": "Custom Field",
			**f,
		})
		doc.insert(ignore_permissions=True)
		print(f"  Created Custom Field: {f['dt']}.{f['fieldname']}")
