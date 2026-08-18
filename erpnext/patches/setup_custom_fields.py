"""Idempotent setup script for custom fields and workflows. Safe to re-run on every deploy.

Run via: docker compose exec -T backend bench --site frontend execute erpnext.patches.setup_custom_fields.execute
Or via bench console and calling execute() manually.
"""
import json

import frappe

from erpnext.stock.responsible_employee import RESPONSIBLE_EMPLOYEE_DIMENSION


def execute():
	create_workflow_states()
	create_workflow_actions()
	create_workflow()
	create_custom_fields_on_item()
	create_item_specification_tab()
	create_custom_fields_on_pr_item()
	create_custom_fields_on_pr()
	create_custom_field_on_qi()
	create_custom_field_on_serial_no()
	remove_flight_test_status_from_serial_no()
	create_additional_attributes_on_serial_no()
	seed_firmware_additional_attribute()
	add_serial_attributes_shortcut()
	create_custom_fields_on_work_order()
	create_custom_fields_on_employee()
	remove_label_templates_from_employee()
	remove_label_templates_from_workplace()
	create_custom_fields_on_so()
	create_custom_fields_on_so_item()
	create_custom_field_on_pallet()
	create_custom_field_on_bpak_template()
	create_custom_fields_on_opportunity()
	create_custom_fields_on_quotation()
	create_custom_fields_on_quotation_item()
	create_custom_fields_on_whatsapp_message()
	setup_whatsapp_user_role()
	create_military_unit_fields()
	create_customer_prospect_link()
	setup_lead_sources()
	setup_lead_permissions()
	setup_lead_next_action_notification()
	remove_duplicate_lead_custom_fields()
	setup_chat_manager_role()
	restore_standard_navbar_items()
	create_responsible_employee_dimension()
	setup_group_access_fields()
	setup_group_access_role()
	setup_project_access_permissions()
	setup_serial_no_write_for_stock_user()
	frappe.db.commit()
	print(
		"Setup complete: PR workflow, custom fields on Item, PR Item, Quality Inspection, Work Order, Sales Order attachments"
	)


def create_workflow_states():
	states = [
		{"workflow_state_name": "Чернетка", "style": "Primary"},
		{"workflow_state_name": "На перевірці", "style": "Warning"},
		{"workflow_state_name": "На затвердженні", "style": "Info"},
		{"workflow_state_name": "Проведено", "style": "Success"},
	]
	for s in states:
		if not frappe.db.exists("Workflow State", s["workflow_state_name"]):
			doc = frappe.get_doc(
				{
					"doctype": "Workflow State",
					"workflow_state_name": s["workflow_state_name"],
					"style": s["style"],
				}
			)
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
			doc = frappe.get_doc(
				{
					"doctype": "Workflow Action Master",
					"workflow_action_name": action_name,
				}
			)
			doc.insert(ignore_permissions=True)
			print(f"  Created Workflow Action: {action_name}")
		else:
			print(f"  Workflow Action exists: {action_name}")


def create_workflow():
	workflow_name = "Purchase Receipt QC Workflow"
	if frappe.db.exists("Workflow", workflow_name):
		print(f"  Workflow exists: {workflow_name}")
		return

	doc = frappe.get_doc(
		{
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
		}
	)
	doc.insert(ignore_permissions=True)
	print(f"  Created Workflow: {workflow_name}")


def create_custom_fields_on_item():
	# Remove old fields from previous iterations
	for old_field in [
		"battery_specs_section",
		"battery_capacity",
		"battery_voltage",
		"cell_type",
		"item_qc_profile",
		"item_specification",
		"label_template",
		"requires_incoming_qc",
	]:
		old_cf = frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": old_field})
		if old_cf:
			frappe.delete_doc("Custom Field", old_cf, force=True)
			print(f"  Removed old Custom Field: Item.{old_field}")

	fields = [
		{
			"dt": "Item",
			"fieldname": "custom_шифр",
			"fieldtype": "Data",
			"label": "Шифр",
			"read_only": 1,
			"insert_after": "item_name",
			"description": "Resolved from Specification Number Template, or denormalized from Specification Parameters",
		},
	]
	_create_custom_fields(fields)


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
		{
			"dt": "Item",
			"fieldname": "specification_number_template",
			"fieldtype": "Link",
			"label": "Specification Number Template",
			"options": "Specification Number Template",
			"insert_after": "label_templates",
		},
	]
	_create_custom_fields(fields)

	existing = frappe.db.exists(
		"Custom Field",
		{"dt": "Item", "fieldname": "specification_number_template"},
	)
	if existing:
		cf = frappe.get_doc("Custom Field", existing)
		if cf.insert_after != "label_templates":
			cf.insert_after = "label_templates"
			cf.save(ignore_permissions=True)


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


def create_custom_fields_on_pr():
	fields = [
		{
			"dt": "Purchase Receipt",
			"fieldname": "packages_section",
			"fieldtype": "Section Break",
			"label": "Packages",
			"insert_after": "supplied_items",
			"collapsible": 1,
		},
		{
			"dt": "Purchase Receipt",
			"fieldname": "packages",
			"fieldtype": "Table",
			"label": "Packages",
			"options": "Purchase Receipt Package",
			"insert_after": "packages_section",
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


def create_custom_field_on_serial_no():
	fields = [
		{
			"dt": "Serial No",
			"fieldname": "inspection_status",
			"fieldtype": "Select",
			"label": "Стан перевірки",
			"options": "\nPass\nFail",
			"insert_after": "status",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"description": "Auto-synced from submitted Quality Inspection",
		},
	]
	_create_custom_fields(fields)


def remove_flight_test_status_from_serial_no():
	cf = frappe.db.exists("Custom Field", {"dt": "Serial No", "fieldname": "flight_test_status"})
	if cf:
		frappe.delete_doc("Custom Field", cf, force=True)
		print("  Removed Custom Field: Serial No.flight_test_status")


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


def create_custom_fields_on_employee():
	fields = [
		{
			"dt": "Employee",
			"fieldname": "shortname",
			"fieldtype": "Data",
			"label": "Shortname",
			"insert_after": "employee_name",
			"unique": 1,
		},
	]
	_create_custom_fields(fields)


def remove_label_templates_from_employee():
	cf = frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "label_templates"})
	if cf:
		frappe.delete_doc("Custom Field", cf, force=True)
		print("  Removed Custom Field: Employee.label_templates")
	else:
		print("  Custom Field already removed: Employee.label_templates")


def remove_label_templates_from_workplace():
	cf = frappe.db.exists("Custom Field", {"dt": "Workplace", "fieldname": "label_templates"})
	if cf:
		frappe.delete_doc("Custom Field", cf, force=True)
		print("  Removed Custom Field: Workplace.label_templates")
	else:
		print("  Custom Field already removed: Workplace.label_templates")


def create_custom_fields_on_so():
	fields = [
		{
			"dt": "Sales Order",
			"fieldname": "attachments_section",
			"fieldtype": "Section Break",
			"label": "Attachments",
			"insert_after": "items",
			"collapsible": 1,
		},
		{
			"dt": "Sales Order",
			"fieldname": "packages",
			"fieldtype": "Table",
			"label": "Packages",
			"options": "Sales Order Package",
			"insert_after": "attachments_section",
		},
		{
			"dt": "Sales Order",
			"fieldname": "pallets",
			"fieldtype": "Table",
			"label": "Pallets",
			"options": "Sales Order Pallet",
			"insert_after": "packages",
		},
		{
			"dt": "Sales Order",
			"fieldname": "attachment_tree_html",
			"fieldtype": "HTML",
			"label": "Attachment Tree",
			"insert_after": "pallets",
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_so_item():
	fields = [
		{
			"dt": "Sales Order Item",
			"fieldname": "source_type",
			"fieldtype": "Select",
			"label": "Source",
			"options": "Direct\nPackage\nBpAK\nPallet",
			"default": "Direct",
			"insert_after": "item_code",
			"read_only": 1,
			"in_list_view": 0,
		},
		{
			"dt": "Sales Order Item",
			"fieldname": "source_package",
			"fieldtype": "Link",
			"label": "Source Package",
			"options": "Package",
			"insert_after": "source_type",
			"read_only": 1,
		},
		{
			"dt": "Sales Order Item",
			"fieldname": "source_bpak",
			"fieldtype": "Link",
			"label": "Source BpAK",
			"options": "BpAK",
			"insert_after": "source_package",
			"read_only": 1,
		},
		{
			"dt": "Sales Order Item",
			"fieldname": "source_pallet",
			"fieldtype": "Link",
			"label": "Source Pallet",
			"options": "Pallet",
			"insert_after": "source_bpak",
			"read_only": 1,
		},
		{
			"dt": "Sales Order Item",
			"fieldname": "source_row_key",
			"fieldtype": "Data",
			"label": "Source Row Key",
			"insert_after": "source_pallet",
			"hidden": 1,
			"read_only": 1,
		},
	]
	_create_custom_fields(fields)


def create_custom_field_on_pallet():
	fields = [
		{
			"dt": "Pallet",
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"label": "Sales Order",
			"options": "Sales Order",
			"insert_after": "status",
			"read_only": 1,
		},
	]
	_create_custom_fields(fields)


def create_custom_field_on_bpak_template():
	fields = [
		{
			"dt": "BpAK Template",
			"fieldname": "custom_шифр",
			"fieldtype": "Data",
			"label": "Шифр",
			"read_only": 1,
			"insert_after": "template_name",
		},
		{
			"dt": "BpAK Template",
			"fieldname": "specification_number_template",
			"fieldtype": "Link",
			"label": "Specification Number Template",
			"options": "Specification Number Template",
			"insert_after": "serial_no_series",
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_opportunity():
	fields = [
		{
			"dt": "Opportunity",
			"fieldname": "deal_tab",
			"fieldtype": "Tab Break",
			"label": "Deal",
			"insert_after": "total",
		},
		{
			"dt": "Opportunity",
			"fieldname": "participants_section",
			"fieldtype": "Section Break",
			"label": "Participants",
			"insert_after": "deal_tab",
		},
		{
			"dt": "Opportunity",
			"fieldname": "participants",
			"fieldtype": "Table",
			"label": "Participants",
			"options": "Opportunity Participant",
			"insert_after": "participants_section",
		},
		{
			"dt": "Opportunity",
			"fieldname": "deal_documents_section",
			"fieldtype": "Section Break",
			"label": "Deal Documents",
			"insert_after": "participants",
		},
		{
			"dt": "Opportunity",
			"fieldname": "deal_documents_html",
			"fieldtype": "HTML",
			"label": "Deal Documents",
			"insert_after": "deal_documents_section",
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_quotation():
	fields = [
		{
			"dt": "Quotation",
			"fieldname": "negotiation_status",
			"fieldtype": "Select",
			"label": "Negotiation Status",
			"options": "\nDraft\nInternal Approval\nSent to Client\nFeedback Received\nNeeds Editing\nResent\nApproved\nPartially Approved\nRejected\nConverted to Sales Order",
			"insert_after": "status",
			"in_standard_filter": 1,
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_quotation_item():
	fields = [
		{
			"dt": "Quotation Item",
			"fieldname": "supply_status",
			"fieldtype": "Select",
			"label": "Supply Status",
			"options": "\nFinished Goods\nNeeds Production\nNeeds R&D\nPartially In Stock\nAwaiting Purchase\nNeeds Technical Approval\nUnavailable",
			"insert_after": "stock_uom",
			"in_list_view": 0,
		},
	]
	_create_custom_fields(fields)


def create_custom_fields_on_whatsapp_message():
	# The WhatsApp Message DocType ships with the frappe_whatsapp app, which is not
	# installed on every site (see apps.json). Without this guard the Custom Field
	# insert raises LinkValidationError and aborts the rest of execute().
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		print("  Skipped WhatsApp Message fields: frappe_whatsapp not installed")
		return

	# Stores the failure reason from Meta's status webhook (e.g. error 131047
	# "Re-engagement message") so the Chat Center can show why a send failed.
	fields = [
		{
			"dt": "WhatsApp Message",
			"fieldname": "status_error",
			"label": "Status Error",
			"fieldtype": "Small Text",
			"insert_after": "status",
			"read_only": 1,
			"no_copy": 1,
		},
	]
	_create_custom_fields(fields)


def setup_whatsapp_user_role():
	"""Dedicated role that grants access to WhatsApp: the Chat Center page, the chat
	bubble, the phone-field icon and the form panel all key off read/create on
	WhatsApp Message (see whatsapp_chat._require_wa_access)."""
	role = "WhatsApp User"
	if not frappe.db.exists("Role", role):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True)
		print(f"  Created Role: {role}")

	perms = {
		"WhatsApp Message": {"read": 1, "create": 1, "write": 1},
		"WhatsApp Chat": {"read": 1, "create": 1, "write": 1},
	}
	for doctype, rights in perms.items():
		if not frappe.db.exists("DocType", doctype):
			print(f"  Skipped perms, DocType missing: {doctype}")
			continue
		existing = frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0})
		if existing:
			print(f"  Custom DocPerm exists: {doctype} / {role}")
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 0,
				**rights,
			}
		).insert(ignore_permissions=True)
		print(f"  Created Custom DocPerm: {doctype} / {role}")

	# WhatsApp access is granted by the dedicated role only — drop the broad Sales
	# grants that predate it.
	for doctype in perms:
		if not frappe.db.exists("DocType", doctype):
			continue
		stale = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "role": ["in", ["Sales User", "Sales Manager"]]},
			pluck="name",
		)
		for name in stale:
			frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
			print(f"  Removed Custom DocPerm: {doctype} / {name}")

	frappe.clear_cache()


def create_military_unit_fields():
	"""«Військова частина» is maintained on the organization, never on the Lead.

	The Lead mirrors it read-only (see Lead.set_military_unit). Sales documents autofill
	it from their party (`erpnext.crm.utils.set_military_unit_from_party`) but stay
	editable, so a one-off deviation can be recorded on the document itself. The Prospect
	grids only display the value of the linked document."""
	fields = [
		{
			"dt": "Prospect",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "company_name",
		},
		{
			"dt": "Customer",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "customer_name",
		},
		{
			"dt": "Opportunity",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "customer_name",
			"in_standard_filter": 1,
		},
		{
			"dt": "Quotation",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "customer_name",
			"in_standard_filter": 1,
		},
		{
			"dt": "Sales Order",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "customer_name",
			"in_standard_filter": 1,
		},
		{
			"dt": "Issue",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "customer",
			"in_standard_filter": 1,
		},
		{
			"dt": "Prospect Lead",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "status",
			"fetch_from": "lead.military_unit",
			"read_only": 1,
			"in_list_view": 1,
		},
		{
			"dt": "Prospect Opportunity",
			"fieldname": "military_unit",
			"fieldtype": "Link",
			"label": "Military Unit",
			"options": "Military Unit",
			"insert_after": "contact_person",
			"fetch_from": "opportunity.military_unit",
			"read_only": 1,
			"in_list_view": 1,
		},
	]
	_create_custom_fields(fields)


def create_customer_prospect_link():
	"""Persisted trace of the Prospect a Customer was converted from.

	`Prospect.make_customer` returns an unsaved mapped doc, so flags set during mapping do
	not survive the client-side save. This field is what lets `Customer.after_insert`
	find the Leads that must be repointed (see prospect.propagate_customer_to_leads)."""
	fields = [
		{
			"dt": "Customer",
			"fieldname": "prospect",
			"fieldtype": "Link",
			"label": "Prospect",
			"options": "Prospect",
			"insert_after": "lead_name",
			"read_only": 1,
			"no_copy": 1,
		},
	]
	_create_custom_fields(fields)


def setup_lead_sources():
	"""«Канал залучення» values.

	Created with Ukrainian names on purpose: these are data records, not code, and their
	English forms ("Online", "Other", ...) are generic msgids whose translation would leak
	into unrelated parts of the UI. `Existing Customer` is stock and is left alone —
	Lead.before_insert still branches on it."""
	sources = [
		"Онлайн",
		"Офлайн",
		"Рекомендації",
		"Холодний контакт",
		"Державні закупівлі",
		"Партнерські організації",
		"Інше",
	]
	for source in sources:
		if frappe.db.exists("Lead Source", source):
			continue
		frappe.get_doc({"doctype": "Lead Source", "source_name": source}).insert(ignore_permissions=True)
		print(f"  Created Lead Source: {source}")


def setup_lead_permissions():
	"""Safety net for deployed sites that already have Custom DocPerm rows on Lead.

	Custom DocPerms shadow the DocType JSON permissions block entirely, so without this the
	`if_owner` restriction shipped in lead.json would silently do nothing."""
	if not frappe.db.exists("Custom DocPerm", {"parent": "Lead"}):
		return

	sales_user = frappe.db.exists("Custom DocPerm", {"parent": "Lead", "role": "Sales User", "permlevel": 0})
	if sales_user:
		frappe.db.set_value("Custom DocPerm", sales_user, {"if_owner": 1, "delete": 0})
		print("  Lead: Sales User restricted to own documents")

	sales_manager = frappe.db.exists(
		"Custom DocPerm", {"parent": "Lead", "role": "Sales Manager", "permlevel": 0}
	)
	if sales_manager:
		frappe.db.set_value("Custom DocPerm", sales_manager, "delete", 0)
		print("  Lead: Sales Manager delete revoked")

	frappe.clear_cache(doctype="Lead")


def setup_lead_next_action_notification():
	"""System reminder to the responsible manager on the day the next action is due."""
	name = "Lead Next Action Reminder"
	if frappe.db.exists("Notification", name):
		print(f"  Notification exists: {name}")
		return

	frappe.get_doc(
		{
			"doctype": "Notification",
			"name": name,
			"subject": "Next action due today: {{ doc.name }}",
			"document_type": "Lead",
			"is_standard": 0,
			"enabled": 1,
			"channel": "System Notification",
			"event": "Days After",
			"date_changed": "next_action_date",
			"days_in_advance": 0,
			"condition": "doc.status not in ('Converted to Opportunity', 'Not Relevant', 'Lost')",
			"message": (
				"Next action for Lead {{ doc.name }} ({{ doc.lead_name }}) is due today.\n\n"
				"{{ doc.next_action }}"
			),
			"recipients": [{"receiver_by_document_field": "lead_owner"}],
		}
	).insert(ignore_permissions=True)
	print(f"  Created Notification: {name}")


def remove_duplicate_lead_custom_fields():
	"""Drop Custom Fields on Lead that a standard field in lead.json now provides.

	The «Запит» fields were first built in the desk UI and only later codified into
	lead.json. Both copies survived, and the Custom Field copy wins the form layout —
	every fork section was rendered at the end of the tab instead of its own place.
	Deleting the Custom Field keeps the data: fieldname == column name, so the values
	simply belong to the standard field from now on.
	"""
	standard = set(frappe.db.get_values("DocField", {"parent": "Lead"}, "fieldname", pluck=True) or [])
	duplicates = [
		cf
		for cf in frappe.get_all("Custom Field", filters={"dt": "Lead"}, fields=["name", "fieldname"])
		if cf.fieldname in standard
	]

	if not duplicates:
		print("  No duplicate Lead custom fields")
		return

	for cf in duplicates:
		frappe.delete_doc("Custom Field", cf.name, ignore_permissions=True, force=True)
		print(f"  Removed duplicate Custom Field: Lead.{cf.fieldname}")

	frappe.clear_cache(doctype="Lead")


def _restore_standard_perms(doctype):
	"""Make sure every standard DocPerm row of `doctype` also exists as a Custom DocPerm.

	Custom DocPerm is all-or-nothing: one row shadows the whole standard permission set. The
	standard rows themselves survive in `tabDocPerm` (migrate re-syncs them from the DocType
	JSON), so they can be copied back verbatim.
	"""
	standard = frappe.get_all("DocPerm", fields="*", filters={"parent": doctype})
	if not standard:
		return

	existing = {
		(p.role, p.permlevel, p.if_owner)
		for p in frappe.get_all(
			"Custom DocPerm",
			fields=["role", "permlevel", "if_owner"],
			filters={"parent": doctype},
		)
	}
	for row in standard:
		if (row.role, row.permlevel, row.if_owner) in existing:
			continue
		custom = frappe.new_doc("Custom DocPerm")
		custom.update(row)
		custom.insert(ignore_permissions=True)
		print(f"  Restored Custom DocPerm: {doctype} / {row.role} (permlevel {row.permlevel})")


def setup_chat_manager_role():
	"""Role that may permanently remove an archived chat with all its messages and files
	(see employee_chat.purge_thread — the check is a plain role-level delete permission on
	Chat Thread, so it can be re-assigned in the Role Permission Manager)."""
	role = "Chat Manager"
	if not frappe.db.exists("Role", role):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
			}
		).insert(ignore_permissions=True)
		print(f"  Created Role: {role}")

	doctype = "Chat Thread"
	if not frappe.db.exists("DocType", doctype):
		print(f"  Skipped perms, DocType missing: {doctype}")
		return

	# The moment one Custom DocPerm row exists for a DocType, frappe's meta REPLACES the
	# standard permissions with the custom ones (Meta.set_custom_permissions). Inserting the
	# Chat Manager row on its own therefore deleted read for System Manager and Employee, and
	# the chat launcher disappeared for everyone (it gates on `can_read` for Chat Thread).
	# Copy the standard rows into Custom DocPerm first, and repair installs that lost them.
	_restore_standard_perms(doctype)

	if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
		print(f"  Custom DocPerm exists: {doctype} / {role}")
		return
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": 0,
			"read": 1,
			"delete": 1,
		}
	).insert(ignore_permissions=True)
	print(f"  Created Custom DocPerm: {doctype} / {role}")


def restore_standard_navbar_items():
	"""Put back the standard entries of the navbar dropdowns.

	On 2026-08-07 a migrate emptied `Navbar Settings.settings_dropdown` down to a single stale
	"Delete Demo Data" row (its action calls `erpnext.demo`, a module that no longer exists), so
	the avatar menu rendered as an empty white box — no My Settings, no Log out. The items are
	seeded only by `frappe.utils.install.add_standard_navbar_items`, which returns early once both
	dropdowns are non-empty, so nothing ever repaired it.

	Matching is by `item_label`, the key frappe itself uses in its navbar patches. Rows that exist
	are left alone (a hidden standard item stays hidden), so this is safe on every deploy.
	"""
	settings = frappe.get_single("Navbar Settings")
	changed = False

	dead = [row for row in settings.settings_dropdown if row.action and "erpnext.demo" in row.action]
	for row in dead:
		settings.settings_dropdown.remove(row)
		changed = True
		print(f"  Removed dead navbar item: {row.item_label}")

	for fieldname, hook in (
		("settings_dropdown", "standard_navbar_items"),
		("help_dropdown", "standard_help_items"),
	):
		have = {(row.item_label or "").strip() for row in settings.get(fieldname)}
		for item in frappe.get_hooks(hook):
			label = (item.get("item_label") or "").strip()
			# The separator has no label and no identity — only add one if the list is empty.
			if not label and have:
				continue
			if label in have:
				continue
			settings.append(fieldname, item)
			have.add(label)
			changed = True
			print(f"  Restored navbar item: {fieldname} / {label or 'Separator'}")

	if not changed:
		print("  Navbar items OK")
		return

	# Deleting a standard item is refused by NavbarSettings.validate outside of a patch run.
	frappe.flags.in_patch = True
	try:
		settings.save(ignore_permissions=True)
	finally:
		frappe.flags.in_patch = False
	frappe.clear_cache()


def create_responsible_employee_dimension():
	"""Track the person a stock item belongs to as an Inventory Dimension.

	Replaces the per-person warehouses under "МО": one R&D warehouse plus a
	Responsible Employee dimension that keeps a per-person balance inside it.
	The doctype creates the Link fields on every stock document and the
	`responsible_employee` column on Stock Ledger Entry by itself.
	"""
	if frappe.db.exists("Inventory Dimension", {"dimension_name": RESPONSIBLE_EMPLOYEE_DIMENSION}):
		print(f"  Inventory Dimension exists: {RESPONSIBLE_EMPLOYEE_DIMENSION}")
		return

	frappe.get_doc(
		{
			"doctype": "Inventory Dimension",
			"dimension_name": RESPONSIBLE_EMPLOYEE_DIMENSION,
			"reference_document": "Employee",
			"apply_to_all_doctypes": 1,
			"reqd": 0,
			"validate_negative_stock": 0,
		}
	).insert(ignore_permissions=True)
	print(f"  Created Inventory Dimension: {RESPONSIBLE_EMPLOYEE_DIMENSION}")


def _create_custom_fields(fields):
	for f in fields:
		existing = frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]})
		if existing:
			print(f"  Custom Field exists: {f['dt']}.{f['fieldname']}")
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Custom Field",
				**f,
			}
		)
		doc.insert(ignore_permissions=True)
		print(f"  Created Custom Field: {f['dt']}.{f['fieldname']}")


def setup_group_access_fields():
	"""Auto-sharing settings on Employee Group.

	A DocShare row can name an Employee Group instead of a user, so one row grants the whole
	group access. These fields let a group lead decide that whatever the group creates is
	shared with the group automatically."""
	_create_custom_fields(
		[
			{
				"dt": "Employee Group",
				"fieldname": "group_access_section",
				"fieldtype": "Section Break",
				"label": "Group Access",
				"insert_after": "employee_list",
			},
			{
				"dt": "Employee Group",
				"fieldname": "auto_share_enabled",
				"fieldtype": "Check",
				"label": "Share Created Documents With Group",
				"description": (
					"Documents created by a member are shared with the whole group automatically."
				),
				"insert_after": "group_access_section",
			},
			{
				"dt": "Employee Group",
				"fieldname": "auto_share_write",
				"fieldtype": "Check",
				"label": "Group Can Edit",
				"description": "Without this the group only gets read access.",
				"depends_on": "auto_share_enabled",
				"insert_after": "auto_share_enabled",
			},
			{
				"dt": "Employee Group",
				"fieldname": "auto_share_doctypes",
				"fieldtype": "Table",
				"label": "Auto-Shared Document Types",
				"options": "Access Group Doctype",
				"depends_on": "auto_share_enabled",
				"insert_after": "auto_share_write",
			},
		]
	)


def setup_group_access_role():
	"""Let a department lead run their own group instead of filing a ticket with the ERP team.

	Employee Group ships with a System Manager-only permission block, which is exactly the
	bottleneck this feature exists to remove."""
	role = "Group Access Manager"
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)
		print(f"  Created Role: {role}")

	doctype = "Employee Group"
	if not frappe.db.exists("DocType", doctype):
		print(f"  Skipped perms, DocType missing: {doctype}")
		return

	# One Custom DocPerm row shadows the whole standard permission block, so copy the
	# standard rows across before adding ours (same trap as setup_chat_manager_role).
	_restore_standard_perms(doctype)

	if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
		print(f"  Custom DocPerm exists: {doctype} / {role}")
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": 0,
			"read": 1,
			"write": 1,
			"create": 1,
			"report": 1,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)
	print(f"  Created Custom DocPerm: {doctype} / {role}")


def setup_project_access_permissions():
	"""Restrict Projects User to its own documents so group sharing decides the rest.

	Stock `project.json` / `task.json` give Projects User a blanket `read`, which is why a
	user today either sees every project or none. With `if_owner` the role sees only what it
	created, and `frappe.share` adds back what is shared with the user or their group —
	db_query's `requires_owner_constraint` branch fetches shared documents specifically for
	this combination.

	`if_owner` rather than dropping `read`: with no read at all db_query takes the
	`only_if_shared` path, which throws "No permission to read" instead of showing an empty
	list to someone who has nothing shared yet.

	`_restore_standard_perms` only runs on the first pass. It de-duplicates on
	`(role, permlevel, if_owner)`, so once `if_owner` is flipped to 1 the standard row looks
	missing and gets re-inserted with `if_owner = 0` — every later deploy would add another
	duplicate, and an unrestricted row silently restores blanket read."""
	role = "Projects User"

	for doctype in ("Project", "Task"):
		if not frappe.db.exists("DocType", doctype):
			continue

		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			_restore_standard_perms(doctype)

		rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "role": role, "permlevel": 0},
			pluck="name",
			order_by="creation asc",
		)
		if not rows:
			continue

		# collapse duplicates left behind by earlier runs of this function
		for extra in rows[1:]:
			frappe.delete_doc("Custom DocPerm", extra, force=True, ignore_permissions=True)
			print(f"  {doctype}: removed duplicate Custom DocPerm for {role}")

		if frappe.db.get_value("Custom DocPerm", rows[0], "if_owner"):
			print(f"  {doctype}: {role} already restricted to own documents")
			continue

		frappe.db.set_value("Custom DocPerm", rows[0], "if_owner", 1)
		frappe.clear_cache(doctype=doctype)
		print(f"  {doctype}: {role} restricted to own documents")


def create_additional_attributes_on_serial_no():
	"""Attach the reusable `Additional Attribute Row` table to Serial No.

	The same dict with a different `dt` attaches per-record key/value metadata to any other
	DocType — no new fields, no new code."""
	fields = [
		{
			"dt": "Serial No",
			"fieldname": "additional_attributes",
			"fieldtype": "Table",
			"label": "Additional Attributes",
			"options": "Additional Attribute Row",
			"insert_after": "inspection_status",
			"description": "Per-unit metadata (firmware build, and anything added later)",
		},
	]
	_create_custom_fields(fields)


def seed_firmware_additional_attribute():
	"""Seed the «Прошивка» attribute and its known builds.

	Data records, not code: Ukrainian on purpose, and users add further builds from the desk
	without a deploy."""
	if not frappe.db.exists("DocType", "Additional Attribute"):
		return

	attribute = "Прошивка"
	if not frappe.db.exists("Additional Attribute", attribute):
		frappe.get_doc(
			{
				"doctype": "Additional Attribute",
				"attribute_name": attribute,
				"description": "Версія прошивки, встановлена на конкретному екземплярі",
			}
		).insert(ignore_permissions=True)
		print(f"  Created Additional Attribute: {attribute}")

	values = [
		("32 біт стара", "32O"),
		("32 біт нова", "32N"),
		("16 біт стара", "16O"),
		("16 біт нова", "16N"),
	]
	for value, abbr in values:
		if frappe.db.exists("Additional Attribute Value", {"attribute": attribute, "value": value}):
			continue
		frappe.get_doc(
			{
				"doctype": "Additional Attribute Value",
				"attribute": attribute,
				"value": value,
				"abbr": abbr,
			}
		).insert(ignore_permissions=True)
		print(f"  Created Additional Attribute Value: {attribute} / {value}")


def add_serial_attributes_shortcut():
	"""Put the «Serial Attributes» page on the Stock workspace.

	Added at runtime instead of editing the stock workspace JSON — that file is upstream's and
	every edit to it is a merge conflict."""
	if not frappe.db.exists("Workspace", "Stock") or not frappe.db.exists("Page", "serial-attributes"):
		return

	label = "Атрибути серійних номерів"
	workspace = frappe.get_doc("Workspace", "Stock")
	if any(s.link_to == "serial-attributes" for s in workspace.shortcuts):
		return

	workspace.append(
		"shortcuts", {"label": label, "type": "Page", "link_to": "serial-attributes", "color": "Blue"}
	)

	content = json.loads(workspace.content or "[]")
	content.append({"id": "serialAttributes", "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
	workspace.content = json.dumps(content)

	workspace.save(ignore_permissions=True)
	print("  Added Stock workspace shortcut: Serial Attributes")


def setup_serial_no_write_for_stock_user():
	"""Let plain stock users fill in serial attributes.

	The «Атрибути серійних номерів» page writes `Additional Attribute Row` children onto the
	Serial No document, so it needs write on Serial No — stock upstream grants Stock User
	read only. Granted as a Custom DocPerm (`setup_custom_perms` copies the standard rules
	first, so Item Manager / Stock Manager keep theirs)."""
	from frappe.permissions import add_permission, update_permission_property

	doctype = "Serial No"
	role = "Stock User"

	if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
		add_permission(doctype, role, 0)

	for ptype in ("read", "write"):
		update_permission_property(doctype, role, 0, ptype, 1, validate=False)

	print(f"  Granted write on {doctype} to {role}")
	frappe.clear_cache()
