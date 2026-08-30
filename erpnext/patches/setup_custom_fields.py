"""Idempotent setup script for custom fields and workflows. Safe to re-run on every deploy.

Run via: docker compose exec -T backend bench --site frontend execute erpnext.patches.setup_custom_fields.execute
Or via bench console and calling execute() manually.
"""
import json

import frappe

from erpnext.stock.responsible_employee import (
	RESPONSIBLE_EMPLOYEE_DIMENSION,
	RESPONSIBLE_EMPLOYEE_FIELD,
)


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
	create_additional_attributes_on_intake()
	seed_firmware_additional_attribute()
	add_serial_attributes_shortcut()
	create_custom_fields_on_work_order()
	create_custom_fields_on_employee()
	create_salary_split_fields()
	create_salary_tax_components()
	create_disability_fields()
	create_identity_fields()
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
	create_callmebot_fields()
	setup_callmebot_default_settings()
	setup_payroll_ua_workspace_card()
	setup_payroll_tax_accounts()
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


def create_salary_split_fields():
	fields = [
		{
			"dt": "Employee",
			"fieldname": "custom_official_salary",
			"fieldtype": "Currency",
			"label": "Official Salary",
			"options": "salary_currency",
			"insert_after": "ctc",
			"description": "The amount accrued officially, before taxes.",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_official_salary_net",
			"fieldtype": "Currency",
			"label": "Accrued to the Card",
			"options": "salary_currency",
			"insert_after": "custom_official_salary",
			"read_only": 1,
			"description": "Calculated: the official salary less PIT 18% and military levy 5%, so 77% of it. The employer pays SSC 22% on top of the official salary — that is not withheld from the employee.",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_cash_salary",
			"fieldtype": "Currency",
			"label": "Cash Salary",
			"options": "salary_currency",
			"insert_after": "custom_official_salary_net",
			"description": "Paid from the cash desk and not taxed. Together with the official part it makes up the full salary.",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_salary_effective_from",
			"fieldtype": "Date",
			"label": "Salary Effective From",
			"insert_after": "custom_cash_salary",
			"description": "The Salary Structure Assignment is created from this date. Defaults to the first day of the current month.",
		},
		{
			"dt": "Additional Salary",
			"fieldname": "custom_pay_in_cash",
			"fieldtype": "Check",
			"label": "Pay in Cash",
			"insert_after": "amount",
			"description": "The amount is moved into the cash payout instead of the official net pay.",
		},
	]
	_create_custom_fields(fields)
	_update_field_texts(fields)
	_make_ctc_read_only()


def create_identity_fields():
	"""РНОКПП (ІПН) — у паспортному блоці картки працівника, поряд із номером паспорта."""
	fields = [
		{
			"dt": "Employee",
			"fieldname": "custom_tax_id",
			"fieldtype": "Data",
			"label": "Tax Number (RNOKPP)",
			"insert_after": "passport_details_section",
			"description": "Ten digits of the taxpayer registration number. It must be unique across employees.",
		},
	]
	_create_custom_fields(fields)
	_update_field_texts(fields)


def create_disability_fields():
	"""Група інвалідності в картці працівника — від неї залежить ставка ЄСВ (8,41% замість 22%)."""
	from erpnext.hr.payroll_tax import DISABILITY_GROUPS

	fields = [
		{
			"dt": "Employee",
			"fieldname": "custom_disability_group",
			"fieldtype": "Select",
			"label": "Disability Group",
			"options": "\n" + "\n".join(DISABILITY_GROUPS),
			"insert_after": "health_details",
			"description": "Any group gives the reduced SSC rate of 8.41% instead of 22%. Keep the MSEC certificate on file.",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_disability_certificate",
			"fieldtype": "Data",
			"label": "MSEC Certificate",
			"insert_after": "custom_disability_group",
			"depends_on": "eval:doc.custom_disability_group",
			"description": "Number of the MSEC certificate or of the expert team decision — the ground for the reduced rate.",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_disability_valid_till",
			"fieldtype": "Date",
			"label": "Disability Valid Till",
			"insert_after": "custom_disability_certificate",
			"depends_on": "eval:doc.custom_disability_group",
			"description": "Leave it empty if the group is set for good.",
		},
	]
	_create_custom_fields(fields)
	_update_field_texts(fields)


def create_salary_tax_components():
	"""ПДФО / військовий збір / ЄСВ — без них листок не знає, що утримати з офіційної частини."""
	from erpnext.hr import payroll_tax

	payroll_tax.ensure_components()


def _update_field_texts(fields):
	"""Підписи й підказки міняються частіше за самі поля, а `_create_custom_fields` наявне поле
	лише пропускає — тож текст оновлюємо окремо."""
	for f in fields:
		name = frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]})

		if not name:
			continue

		values = {key: f[key] for key in ("label", "description", "options") if key in f}
		current = frappe.db.get_value("Custom Field", name, list(values), as_dict=True)

		if values and (not current or any(current.get(key) != value for key, value in values.items())):
			frappe.db.set_value("Custom Field", name, values)
			print(f"  Updated Custom Field text: {f['dt']}.{f['fieldname']}")


def _make_ctc_read_only():
	"""CTC becomes the sum of the official and cash parts, so nobody may type it in by hand."""
	existing = frappe.db.exists(
		"Property Setter", {"doc_type": "Employee", "field_name": "ctc", "property": "read_only"}
	)
	if existing:
		print("  Property Setter exists: Employee.ctc.read_only")
		return

	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": "Employee",
			"field_name": "ctc",
			"property": "read_only",
			"property_type": "Check",
			"value": "1",
		}
	).insert(ignore_permissions=True)
	print("  Created Property Setter: Employee.ctc.read_only")


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
	existing = frappe.db.exists("Inventory Dimension", {"dimension_name": RESPONSIBLE_EMPLOYEE_DIMENSION})
	if existing:
		print(f"  Inventory Dimension exists: {RESPONSIBLE_EMPLOYEE_DIMENSION}")
		enforce_responsible_employee_stock(existing)
	else:
		frappe.get_doc(
			{
				"doctype": "Inventory Dimension",
				"dimension_name": RESPONSIBLE_EMPLOYEE_DIMENSION,
				"reference_document": "Employee",
				"apply_to_all_doctypes": 1,
				"reqd": 0,
				"validate_negative_stock": 1,
			}
		).insert(ignore_permissions=True)
		print(f"  Created Inventory Dimension: {RESPONSIBLE_EMPLOYEE_DIMENSION}")

	relax_rejected_responsible_employee()
	create_serial_no_responsible_field()


def enforce_responsible_employee_stock(name):
	"""Turn on the per-person negative stock check on an already created dimension.

	Without it the dimension is only a label: a person could hand over more than they
	hold as long as the warehouse as a whole covered it, and their balance silently went
	negative. `StockLedgerEntry.validate_inventory_dimension_negative_stock` does the
	check, but only for dimensions that ask for it.

	`validate_negative_stock` is one of the few fields `InventoryDimension.do_not_update_document`
	still allows to change once stock transactions exist, so this is safe to flip late.
	"""
	if frappe.db.get_value("Inventory Dimension", name, "validate_negative_stock"):
		print("  Responsible Employee already validates negative stock")
		return

	frappe.db.set_value("Inventory Dimension", name, "validate_negative_stock", 1)
	frappe.clear_cache()
	print("  Responsible Employee now validates negative stock")


def create_serial_no_responsible_field():
	"""Store the responsible employee on the Serial No itself.

	The dimension lives on Stock Ledger Entry, and `get_inventory_documents()` excludes
	Serial No from the doctypes it generates fields on, so custody of a single serial was
	only reachable through a three table join. A serial is one unit, so the holder is a
	property of the serial — kept in step with `warehouse` by
	`erpnext.stock.responsible_employee.set_serial_no_responsible`.
	"""
	_create_custom_fields(
		[
			{
				"dt": "Serial No",
				"fieldname": RESPONSIBLE_EMPLOYEE_FIELD,
				"fieldtype": "Link",
				"options": "Employee",
				"label": "Responsible Employee",
				"insert_after": "warehouse",
				"read_only": 1,
				"search_index": 1,
				"in_standard_filter": 1,
			}
		]
	)


def relax_rejected_responsible_employee():
	"""Drop the stock "mandatory when something was rejected" rule from the dimension.

	`InventoryDimension.get_dimension_fields()` hardcodes
	`mandatory_depends_on = "eval:doc.rejected_qty > 0"` on the `rejected_<dimension>` field of
	Purchase Receipt / Purchase Invoice Item, no matter whether the dimension itself is `reqd`.
	Ours is not: custody only has to be recorded inside the R&D warehouse, and that is enforced
	server-side by `erpnext.stock.responsible_employee.validate_responsible_employee`, which also
	fills the field with the Employee of the current user. The client-side rule fired on every
	rejected row of every warehouse and blocked the save before the server ever ran.
	"""
	fields = frappe.get_all(
		"Custom Field",
		filters={
			"fieldname": f"rejected_{RESPONSIBLE_EMPLOYEE_FIELD}",
			"mandatory_depends_on": ("!=", ""),
		},
		pluck="name",
	)

	for name in fields:
		frappe.db.set_value(
			"Custom Field", name, {"mandatory_depends_on": "", "reqd": 0}, update_modified=False
		)
		print(f"  Cleared mandatory_depends_on: {name}")

	if fields:
		frappe.clear_cache()


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


def create_additional_attributes_on_intake():
	"""Attach the same reusable table to the documents that bring serial numbers into stock.

	The receiving clerk types the values on the `Purchase Receipt`; they are copied onto every
	`Serial and Batch Bundle` the receipt generates and from there onto every serial. The table
	sits on the receipt, not on its item rows, because a child table inside a child table is not
	something Frappe renders.

	The bundle carries the same table, which doubles as the per-item override (open the bundle
	from the row) and covers the paths that never see a Purchase Receipt at all — the selector
	dialog, the CSV import and the scanner."""
	fields = [
		{
			"dt": "Purchase Receipt",
			"fieldname": "additional_attributes_section",
			"fieldtype": "Section Break",
			"label": "Additional Attributes",
			"insert_after": "items",
			"collapsible": 1,
		},
		{
			"dt": "Purchase Receipt",
			"fieldname": "additional_attributes",
			"fieldtype": "Table",
			"label": "Additional Attributes",
			"options": "Additional Attribute Row",
			"insert_after": "additional_attributes_section",
			"description": "Applied to every serial number this receipt brings in",
		},
		{
			"dt": "Serial and Batch Bundle",
			"fieldname": "additional_attributes",
			"fieldtype": "Table",
			"label": "Additional Attributes",
			"options": "Additional Attribute Row",
			"insert_after": "entries",
			"description": "Applied to every serial number in this bundle on submit",
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


def create_callmebot_fields():
	"""Per-user CallMeBot credentials on Notification Settings.

	Notification Settings is already the per-user notification preferences document (its name is
	the user id), and every user may read/write their own via its `has_permission`. WhatsApp is
	just one more delivery channel, so the fields belong next to the existing system/email
	toggles rather than on User."""
	fields = [
		{
			"dt": "Notification Settings",
			"fieldname": "callmebot_section",
			"fieldtype": "Section Break",
			"label": "WhatsApp Notifications (CallMeBot)",
			"insert_after": "energy_points_system_notifications",
			"description": "Mirror desk notifications to WhatsApp through the free CallMeBot relay",
		},
		{
			"dt": "Notification Settings",
			"fieldname": "callmebot_enabled",
			"fieldtype": "Check",
			"label": "Send notifications to WhatsApp",
			"insert_after": "callmebot_section",
		},
		{
			"dt": "Notification Settings",
			"fieldname": "callmebot_phone",
			"fieldtype": "Data",
			"label": "CallMeBot Phone",
			"insert_after": "callmebot_enabled",
			"depends_on": "eval:doc.callmebot_enabled",
			"mandatory_depends_on": "eval:doc.callmebot_enabled",
			"description": "Phone number with country code, digits only (for example 380636400706)",
		},
		{
			"dt": "Notification Settings",
			"fieldname": "callmebot_column",
			"fieldtype": "Column Break",
			"insert_after": "callmebot_phone",
		},
		{
			"dt": "Notification Settings",
			"fieldname": "callmebot_api_key",
			"fieldtype": "Password",
			"label": "CallMeBot API Key",
			"insert_after": "callmebot_column",
			"depends_on": "eval:doc.callmebot_enabled",
			"mandatory_depends_on": "eval:doc.callmebot_enabled",
			"no_copy": 1,
			"description": "Key sent back by the bot after you activate it from your phone",
		},
	]
	_create_custom_fields(fields)
	_migrate_callmebot_keys_to_auth()


def _migrate_callmebot_keys_to_auth():
	"""Move keys stored while `callmebot_api_key` was a plain Data field into `__Auth`.

	A Password field keeps only a `*****` dummy in its own column, so any row still holding a
	real key is one written before the fieldtype change. Encrypt it and blank out the column."""
	if not frappe.db.has_column("Notification Settings", "callmebot_api_key"):
		return

	from frappe.utils.password import set_encrypted_password

	rows = frappe.db.sql(
		"""select name, callmebot_api_key from `tabNotification Settings`
		where ifnull(callmebot_api_key, '') != '' and callmebot_api_key not rlike '^[*]+$'""",
		as_dict=True,
	)
	for row in rows:
		key = (row.callmebot_api_key or "").strip()
		if not key:
			continue
		set_encrypted_password("Notification Settings", row.name, key, "callmebot_api_key")
		frappe.db.set_value(
			"Notification Settings", row.name, "callmebot_api_key", "*" * len(key), update_modified=False
		)

	if rows:
		print(f"  Encrypted {len(rows)} CallMeBot API key(s) into __Auth")


def setup_callmebot_default_settings():
	"""Initialize CallMeBot Settings Single DocType with standard privacy templates."""
	if not frappe.db.exists("DocType", "CallMeBot Settings"):
		return

	try:
		settings = frappe.get_doc("CallMeBot Settings")
		modified = False

		if not settings.default_message:
			settings.default_message = "У вас нове сповіщення у ERPnext"
			settings.privacy_mode = 1
			settings.include_link = 1
			modified = True

		if not settings.templates:
			settings.append(
				"templates",
				{
					"notification_type": "Assignment",
					"template": "На вас призначено нове завдання",
					"include_link": 1,
				},
			)
			settings.append(
				"templates",
				{
					"notification_type": "Mention",
					"template": "Вас згадали у коментарі",
					"include_link": 1,
				},
			)
			settings.append(
				"templates",
				{
					"notification_type": "Share",
					"template": "Вам надано доступ до документу",
					"include_link": 1,
				},
			)
			modified = True

		if modified:
			settings.save(ignore_permissions=True)
			print("  Initialized CallMeBot Settings default privacy templates")
	except Exception as e:
		print(f"  Warning: could not initialize CallMeBot Settings: {e}")


PAYROLL_UA_CARD_LABELS = ("Payroll UA", "Payrol UA")
PAYROLL_UA_CARD = "Payrol UA"
PAYROLL_UA_BLOCK_ID = "payrollUaCard"
# (заголовок, тип, куди) — табель відкривається сторінкою, решта доктайпами.
PAYROLL_UA_LINKS = (
	("Salary Advance", "DocType", "Salary Advance"),
	("Payroll Sheet", "DocType", "Payroll Sheet"),
	("Management Payroll Sheet", "DocType", "Management Payroll Sheet"),
	("Salary Change", "DocType", "Salary Change"),
	("Attendance Sheet", "Page", "attendance-sheet"),
	("Salary Approval", "DocType", "Salary Approval"),
	("Payroll Tax Settings", "DocType", "Payroll Tax Settings"),
)

# Помилково додані посилання прибираються з картки, інакше вони лишаються на робочих сайтах.
PAYROLL_UA_DROP = ("Attendance Sheet Approval",)


def setup_payroll_ua_workspace_card():
	"""Тримає картку «Зарплата» на робочому просторі HR повною.

	Простір редагується в десктопі, тож його копія в базі з репозиторієм уже не синхронізується —
	картка доповнюється тут, ідемпотентно: наявні посилання лишаються, бракуючі дописуються
	в кінець картки."""
	if not frappe.db.exists("Workspace", "HR"):
		return

	workspace = frappe.get_doc("Workspace", "HR")
	links = list(workspace.links)
	start = next(
		(
			index
			for index, link in enumerate(links)
			if link.type == "Card Break" and link.label in PAYROLL_UA_CARD_LABELS
		),
		None,
	)

	if start is None:
		start = len(links)
		links.append(frappe._dict(type="Card Break", label=PAYROLL_UA_CARD, link_count=0, hidden=0))

	# Кінець картки — наступний розділювач: посилання дописуються всередину неї, а не в хвіст
	# усього простору, інакше вони опиняться в чужій картці.
	end = next(
		(index for index in range(start + 1, len(links)) if links[index].type == "Card Break"),
		len(links),
	)
	dropped = [
		link for link in links[start + 1 : end] if link.type == "Link" and link.link_to in PAYROLL_UA_DROP
	]
	for link in dropped:
		links.remove(link)

	end -= len(dropped)
	present = {link.link_to for link in links[start + 1 : end] if link.type == "Link"}
	missing = [
		(label, link_type, link_to)
		for label, link_type, link_to in PAYROLL_UA_LINKS
		if link_to not in present
		and (link_type != "DocType" or frappe.db.exists("DocType", link_to))
		and (link_type != "Page" or frappe.db.exists("Page", link_to))
	]

	if not (missing or dropped):
		return

	links[end:end] = [
		frappe._dict(
			type="Link",
			label=label,
			link_type=link_type,
			link_to=link_to,
			link_count=0,
			hidden=0,
			onboard=0,
		)
		for label, link_type, link_to in missing
	]

	workspace.set("links", [])
	for index, link in enumerate(links, start=1):
		# Порядок задається наново: перенесені рядки несуть старий `idx`, і з ним картка
		# розсипається на два однакові номери.
		row = workspace.append("links", link)
		row.idx = index

	content = json.loads(workspace.content or "[]")
	if not any(block.get("data", {}).get("card_name") in PAYROLL_UA_CARD_LABELS for block in content):
		content.append(
			{"id": PAYROLL_UA_BLOCK_ID, "type": "card", "data": {"card_name": PAYROLL_UA_CARD, "col": 4}}
		)
		workspace.content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)

	workspace.save(ignore_permissions=True)

	if missing:
		print(f"  Added HR workspace links: {', '.join(label for label, _type, _to in missing)}")

	if dropped:
		print(f"  Removed HR workspace links: {', '.join(link.link_to for link in dropped)}")


# Податок → (назва рахунку, під яким його видно в плані рахунків, рахунок-батько за типом).
PAYROLL_TAX_ACCOUNTS = {
	"ПДФО": "ПДФО до сплати",
	"Військовий збір": "Військовий збір до сплати",
	"ЄСВ (роботодавець)": "ЄСВ до сплати",
}


def setup_payroll_tax_accounts():
	"""Окремий рахунок «до сплати» на кожен зарплатний податок.

	Раніше ПДФО і військовий збір вели на зарплатний пасив разом із самою зарплатою, тож
	борг перед бюджетом ніде не було видно. Рахунки створюються під групою податків компанії
	й прописуються в самі компоненти — далі бухгалтер міняє їх у довіднику."""
	for company in frappe.get_all("Company", pluck="name"):
		parent = _tax_parent_account(company)

		if not parent:
			continue

		payable = frappe.get_cached_value("Company", company, "default_payroll_payable_account")

		for component, account_name in PAYROLL_TAX_ACCOUNTS.items():
			if not frappe.db.exists("Salary Component", component):
				continue

			account = _ensure_tax_account(company, parent, account_name)

			if not account:
				continue

			existing = frappe.db.get_value(
				"Salary Component Account", {"parent": component, "company": company}, ["name", "account"]
			)

			# Свій рахунок бухгалтера не чіпаємо — міняємо лише те, що вело на спільний пасив.
			if existing and existing[1] not in (None, "", payable):
				continue

			if existing:
				frappe.db.set_value("Salary Component Account", existing[0], "account", account)
				print(f"  {component}: account -> {account}")
				continue

			doc = frappe.get_doc("Salary Component", component)
			doc.append("accounts", {"company": company, "account": account})
			doc.save(ignore_permissions=True)
			print(f"  {component}: account set to {account}")


def _tax_parent_account(company):
	"""Група, під якою живуть податкові зобов'язання компанії."""
	return frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": "Liability", "account_type": "Tax"},
		"name",
	) or frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": "Liability", "account_name": ["like", "%Поточні%"]},
		"name",
	)


def _ensure_tax_account(company, parent, account_name):
	existing = frappe.db.get_value(
		"Account", {"company": company, "account_name": account_name, "is_group": 0}, "name"
	)

	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"company": company,
			"parent_account": parent,
			"root_type": "Liability",
			"account_type": "Tax",
			"is_group": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	print(f"  Created account: {doc.name}")

	return doc.name
