import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

CUSTOM_FIELDS = {
	"Buying Settings": [
		{
			"fieldname": "custom_procurement_approval_section",
			"fieldtype": "Section Break",
			"label": "Procurement Approval",
			"insert_after": "fixed_email",
		},
		{
			"fieldname": "custom_ceo_approval_threshold",
			"fieldtype": "Currency",
			"label": "CEO Approval Threshold",
			"default": "15000",
			"reqd": 1,
			"insert_after": "custom_procurement_approval_section",
		},
		{
			"fieldname": "custom_final_approver_1",
			"fieldtype": "Link",
			"label": "CEO Approver 1",
			"options": "User",
			"insert_after": "custom_ceo_approval_threshold",
		},
		{
			"fieldname": "custom_procurement_approval_column",
			"fieldtype": "Column Break",
			"insert_after": "custom_final_approver_1",
		},
		{
			"fieldname": "custom_final_approver_2",
			"fieldtype": "Link",
			"label": "CEO Approver 2",
			"options": "User",
			"insert_after": "custom_procurement_approval_column",
		},
	],
	"Material Request": [
		{
			"fieldname": "custom_procurement_comment",
			"fieldtype": "Text Editor",
			"label": "Коментар",
			"insert_after": "items",
		},
		{
			"fieldname": "custom_procurement_participants",
			"fieldtype": "Small Text",
			"label": "Procurement Participants",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"insert_after": "per_received",
		},
		{
			"fieldname": "custom_procurement_completion_status",
			"fieldtype": "Select",
			"label": "Procurement Status",
			"options": "Підготовка\nПогодження\nОчікує оплату\nОчікує надходження\nЗавершено",
			"default": "Підготовка",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"insert_after": "custom_procurement_participants",
		},
		{
			"fieldname": "custom_procurement_initiator_user",
			"fieldtype": "Link",
			"label": "Material Request Initiator",
			"options": "User",
			"default": "__user",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "custom_task",
		},
		{
			"fieldname": "custom_items_already_purchased",
			"fieldtype": "Check",
			"label": "Items Already Purchased",
			"insert_after": "custom_procurement_initiator_user",
		},
		{
			"fieldname": "custom_prepaid_purchase_note",
			"fieldtype": "Small Text",
			"label": "Prepaid Purchase Note",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.custom_items_already_purchased",
			"insert_after": "custom_items_already_purchased",
		},
		{
			"fieldname": "custom_purchase_receipts_section",
			"fieldtype": "Section Break",
			"label": "Purchase Receipt Files",
			"depends_on": "eval:doc.custom_items_already_purchased",
			"insert_after": "set_warehouse",
		},
		{
			"fieldname": "custom_purchase_receipts",
			"fieldtype": "Table",
			"label": "Purchase Receipt Files",
			"options": "Consolidated Purchase Supplier Invoice",
			"depends_on": "eval:doc.custom_items_already_purchased",
			"mandatory_depends_on": "eval:doc.custom_items_already_purchased",
			"insert_after": "custom_purchase_receipts_section",
		},
	],
	"Purchase Order": [
		{
			"fieldname": "custom_procurement_participants",
			"fieldtype": "Small Text",
			"label": "Procurement Participants",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"insert_after": "per_received",
		},
		{
			"fieldname": "custom_procurement_completion_status",
			"fieldtype": "Select",
			"label": "Procurement Status",
			"options": "Підготовка\nПогодження\nОчікує оплату\nОчікує надходження\nЗавершено",
			"default": "Підготовка",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"insert_after": "custom_procurement_participants",
		},
		{
			"fieldname": "custom_consolidated_purchase_order",
			"fieldtype": "Link",
			"label": "Consolidated Purchase Order",
			"options": "Consolidated Purchase Order",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"insert_after": "supplier_name",
		},
		{
			"fieldname": "custom_items_already_purchased",
			"fieldtype": "Check",
			"label": "Items Already Purchased",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "custom_consolidated_purchase_order",
		},
		{
			"fieldname": "custom_prepaid_purchase_note",
			"fieldtype": "Small Text",
			"label": "Prepaid Purchase Note",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.custom_items_already_purchased",
			"insert_after": "custom_items_already_purchased",
		},
	],
	"Purchase Order Item": [
		{
			"fieldname": "custom_consolidated_purchase_order_item",
			"fieldtype": "Data",
			"label": "Consolidated Purchase Order Item",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"insert_after": "material_request_item",
		},
	],
	"Purchase Receipt": [
		{
			"fieldname": "custom_ttn_section",
			"fieldtype": "Section Break",
			"label": "ТТН",
			"depends_on": "eval:!doc.is_return",
			"insert_after": "supplier_warehouse",
		},
		{
			"fieldname": "custom_delivery_method",
			"fieldtype": "Data",
			"label": "Спосіб доставки",
			"depends_on": "eval:!doc.is_return",
			"no_copy": 1,
			"insert_after": "custom_ttn_section",
		},
		{
			"fieldname": "custom_ttn_column",
			"fieldtype": "Column Break",
			"depends_on": "eval:!doc.is_return",
			"insert_after": "custom_delivery_method",
		},
		{
			"fieldname": "custom_waybill_number",
			"fieldtype": "Data",
			"label": "Номер накладної",
			"depends_on": "eval:!doc.is_return",
			"no_copy": 1,
			"insert_after": "custom_ttn_column",
		},
		{
			# Keep the legacy attachment table hidden so existing TTN files are not lost.
			"fieldname": "custom_ttn_files",
			"fieldtype": "Table",
			"label": "TTN",
			"options": "Consolidated Purchase Supplier Invoice",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "custom_waybill_number",
		},
	],
	"Purchase Invoice": [
		{
			"fieldname": "custom_consolidated_purchase_order",
			"fieldtype": "Link",
			"label": "Consolidated Purchase Order",
			"options": "Consolidated Purchase Order",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"insert_after": "supplier_name",
		},
		{
			"fieldname": "custom_paid_outside_company",
			"fieldtype": "Check",
			"label": "Payer",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "custom_consolidated_purchase_order",
		},
		{
			"fieldname": "custom_external_payer",
			"fieldtype": "Link",
			"label": "Paid by Initiator",
			"options": "User",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.custom_paid_outside_company",
			"insert_after": "custom_paid_outside_company",
		},
		{
			"fieldname": "custom_external_payment_note",
			"fieldtype": "Small Text",
			"label": "External Payment Note",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.custom_paid_outside_company",
			"insert_after": "custom_external_payer",
		},
	],
}

LEGACY_CLIENT_SCRIPT_NAME = "Закупівлі: погодження замовлення на придбання"
CLIENT_SCRIPT_NAME = "Закупівлі: погодження зведеного замовлення на придбання"
CLIENT_SCRIPT = r"""
frappe.ui.form.on("Consolidated Purchase Order", {
	before_workflow_action(frm) {
		const action = frm.selected_workflow_action;
		const actionsRequiringReason = [
			"Повернути на доопрацювання",
			"Відхилити",
		];

		if (!actionsRequiringReason.includes(action)) {
			return;
		}

		return new Promise((resolve, reject) => {
			let confirmed = false;
			const dialog = new frappe.ui.Dialog({
				title: __("Reason"),
				fields: [
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Reason"),
						reqd: 1,
					},
				],
				primary_action_label: __("Confirm"),
				primary_action(values) {
					const reason = (values.reason || "").trim();
					if (!reason) {
						frappe.msgprint(__("Enter the reason for the decision."));
						return;
					}

					confirmed = true;
					frm.doc.workflow_action_reason = reason;
					frappe.dom.freeze();
					dialog.hide();
					resolve();
				},
			});

			dialog.$wrapper.on("hidden.bs.modal", () => {
				if (!confirmed) {
					frm.selected_workflow_action = null;
					reject();
				}
			});
			frappe.dom.unfreeze();
			dialog.show();
		});
	},
});
""".strip()

MATERIAL_REQUEST_CLIENT_SCRIPT_NAME = "Закупівлі: дії замовлення матеріалів лише для закупівельника"
MATERIAL_REQUEST_CLIENT_SCRIPT = r"""
frappe.ui.form.on("Material Request", {
	setup(frm) {
		const fileField = frappe.meta.get_docfield(
			"Consolidated Purchase Supplier Invoice",
			"invoice_document",
			frm.doc.name
		);
		fileField.formatter = (value, df, options, doc) => {
			const fileName = value || get_purchase_receipt_file_name(doc.invoice_pdf);
			if (!fileName || !doc.invoice_pdf) return "";
			return `<a href="${frappe.utils.escape_html(doc.invoice_pdf)}" target="_blank">${frappe.utils.escape_html(
				fileName
			)}</a>`;
		};
	},

	refresh(frm) {
		configure_purchase_receipts_grid(frm);
		setTimeout(() => configure_purchase_receipts_grid(frm), 100);
		if (frappe.user_roles.includes("Закупівельник")) {
			restrict_duplicate_consolidated_order(frm);
			return;
		}

		const restrictedActions = [
			"Purchase Order",
			"Request for Quotation",
			"Supplier Quotation",
		];
		setTimeout(() => {
			for (const action of restrictedActions) {
				frm.remove_custom_button(__(action), __("Create"));
			}
		}, 0);
	},

	custom_items_already_purchased(frm) {
		frm.set_value(
			"custom_prepaid_purchase_note",
			frm.doc.custom_items_already_purchased
				? __(
					"The materials have already been purchased. Review the attached receipts and verify suppliers and prices."
				)
				: null
		);
	},
});

frappe.ui.form.on("Consolidated Purchase Supplier Invoice", {
	invoice_pdf(frm, cdt, cdn) {
		if (frm.doctype !== "Material Request") return;
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "invoice_document", get_purchase_receipt_file_name(row.invoice_pdf));
		if (!row.invoice_pdf || row.invoice_pdf.split("?")[0].toLowerCase().endsWith(".pdf")) return;

		frappe.model.set_value(cdt, cdn, "invoice_pdf", null);
		frappe.msgprint({
			title: __("Unsupported File Format"),
			message: __("The purchase receipt must be a PDF file."),
			indicator: "red",
		});
	},
});

function configure_purchase_receipts_grid(frm) {
	const field = frm.get_field("custom_purchase_receipts");
	if (!field || !field.grid) return;
	field.grid.update_docfield_property("invoice_pdf", "options", {
		restrictions: { allowed_file_types: [".pdf"] },
		allow_web_link: false,
	});
	field.grid.update_docfield_property("supplier", "hidden", 1);
	field.grid.update_docfield_property("supplier", "in_list_view", 0);
	field.grid.set_column_disp("supplier", false);
	field.grid.wrapper.find(".grid-heading-row .row-index span").text("\u2116");
}

function get_purchase_receipt_file_name(fileUrl) {
	if (!fileUrl) return null;
	const path = fileUrl.split("?")[0];
	return decodeURIComponent(path.substring(path.lastIndexOf("/") + 1));
}

function restrict_duplicate_consolidated_order(frm) {
	if (frm.doc.docstatus !== 1 || frm.doc.material_request_type !== "Purchase") return;
	frappe
		.call({
			method: "erpnext.buying.procurement_automation.get_existing_consolidated_purchase_order",
			args: { source_name: frm.doc.name },
		})
		.then((response) => {
			if (!response.message) return;
			frm.remove_custom_button(__("Purchase Order"), __("Create"));
		});
}
""".strip()


def after_migrate():
	sync_procurement_custom_fields()

	from erpnext.buying.procurement_workflow import sync_procurement_workflow
	from erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order import (
		sync_all_consolidated_purchase_order_progress,
	)
	from erpnext.buying.procurement_final_approval import (
		sync_existing_approval_thresholds,
		sync_existing_final_approval_documents,
	)
	from erpnext.buying.procurement_automation import (
		apply_rules_to_existing_procurement_documents,
		sync_all_procurement_participants,
		sync_existing_purchase_invoice_external_payment_details,
	)

	sync_procurement_workflow()
	apply_rules_to_existing_procurement_documents()
	sync_existing_approval_thresholds()
	sync_existing_final_approval_documents()
	sync_existing_purchase_invoice_external_payment_details()
	sync_all_consolidated_purchase_order_progress()
	sync_all_procurement_participants()
	_sync_client_scripts()
	_sync_list_fields()
	_sync_consolidated_material_requests()
	frappe.clear_cache(doctype="Material Request")
	frappe.clear_cache(doctype="Buying Settings")
	frappe.clear_cache(doctype="Purchase Order")
	frappe.clear_cache(doctype="Purchase Order Item")
	frappe.clear_cache(doctype="Purchase Receipt")
	frappe.clear_cache(doctype="Purchase Invoice")
	frappe.clear_cache(doctype="Consolidated Purchase Order")
	frappe.clear_cache(doctype="Workspace")


def sync_procurement_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, update=True)


def _sync_consolidated_material_requests():
	if not frappe.db.table_exists("Consolidated Purchase Order"):
		return

	parents = frappe.get_all("Consolidated Purchase Order", pluck="name")
	for parent in parents:
		material_requests = frappe.get_all(
			"Consolidated Purchase Order Item",
			filters={"parent": parent, "material_request": ["is", "set"]},
			pluck="material_request",
			distinct=True,
		)
		material_request = material_requests[0] if len(material_requests) == 1 else None
		frappe.db.set_value(
			"Consolidated Purchase Order",
			parent,
			"material_request",
			material_request,
			update_modified=False,
		)


def _sync_client_scripts():
	if frappe.db.exists("Client Script", LEGACY_CLIENT_SCRIPT_NAME):
		legacy_script = frappe.get_doc("Client Script", LEGACY_CLIENT_SCRIPT_NAME)
		legacy_script.enabled = 0
		legacy_script.save(ignore_permissions=True)

	_ensure_client_script(CLIENT_SCRIPT_NAME, "Consolidated Purchase Order", CLIENT_SCRIPT)
	_ensure_client_script(
		MATERIAL_REQUEST_CLIENT_SCRIPT_NAME,
		"Material Request",
		MATERIAL_REQUEST_CLIENT_SCRIPT,
	)


def _ensure_client_script(name, doctype, script):
	if frappe.db.exists("Client Script", name):
		doc = frappe.get_doc("Client Script", name)
	else:
		doc = frappe.new_doc("Client Script")
		doc.name = name
	doc.dt = doctype
	doc.view = "Form"
	doc.enabled = 1
	doc.script = script
	_save(doc)


def _sync_list_fields():
	_ensure_property_setter("workflow_state", "label", "Approval Stage", "Data")
	_ensure_property_setter("workflow_state", "in_list_view", "1", "Check")
	_ensure_property_setter("company", "in_list_view", "0", "Check")
	_ensure_property_setter("procurement_completion_status", "label", "Status", "Data")
	_ensure_property_setter("procurement_completion_status", "in_list_view", "1", "Check")
	_sync_consolidated_purchase_order_list_view()


def _sync_consolidated_purchase_order_list_view():
	fields = [
		{"fieldname": "name", "label": "ID"},
		{"fieldname": "workflow_state", "label": "Approval Stage"},
		{"fieldname": "procurement_completion_status", "label": "Status"},
		{"fieldname": "transaction_date", "label": "Date"},
		{"fieldname": "payment_receipts_progress", "label": "Payment"},
		{"fieldname": "grand_total", "label": "Grand Total"},
	]

	if frappe.db.exists("List View Settings", "Consolidated Purchase Order"):
		doc = frappe.get_doc("List View Settings", "Consolidated Purchase Order")
	else:
		doc = frappe.new_doc("List View Settings")
		doc.name = "Consolidated Purchase Order"

	doc.fields = json.dumps(fields)
	doc.total_fields = "7"
	_save(doc)


def _ensure_property_setter(fieldname, property_name, value, property_type):
	filters = {
		"doc_type": "Consolidated Purchase Order",
		"field_name": fieldname,
		"property": property_name,
	}
	name = frappe.db.exists("Property Setter", filters)
	if name:
		doc = frappe.get_doc("Property Setter", name)
		doc.value = value
		doc.property_type = property_type
		doc.is_system_generated = 1
		doc.save(ignore_permissions=True)
		return
	make_property_setter("Consolidated Purchase Order", fieldname, property_name, value, property_type)


def _save(doc):
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
