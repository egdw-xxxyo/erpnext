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
	create_custom_fields_on_pr()
	create_custom_field_on_qi()
	create_custom_field_on_serial_no()
	remove_flight_test_status_from_serial_no()
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
