import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

CUSTOM_FIELDS = {
	"Material Request": [
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
	],
	"Purchase Order": [
		{
			"fieldname": "custom_procurement_workflow_reason",
			"fieldtype": "Small Text",
			"label": "Decision Reason",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "status",
		},
		{
			"fieldname": "custom_current_assignees",
			"fieldtype": "Data",
			"label": "Current Assignee",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "custom_procurement_workflow_reason",
		},
	],
}

CLIENT_SCRIPT_NAME = "Закупівлі: погодження замовлення на придбання"
CLIENT_SCRIPT = r"""
frappe.ui.form.on("Purchase Order", {
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
					frm.doc.custom_procurement_workflow_reason = reason;
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
	refresh(frm) {
		if (frappe.user_roles.includes("Закупівельник")) {
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
});
""".strip()


def after_migrate():
	create_custom_fields(CUSTOM_FIELDS, update=True)

	from erpnext.buying.procurement_workflow import sync_procurement_workflow

	sync_procurement_workflow()
	_sync_client_scripts()
	_sync_list_fields()
	frappe.clear_cache(doctype="Material Request")
	frappe.clear_cache(doctype="Purchase Order")


def _sync_client_scripts():
	_ensure_client_script(CLIENT_SCRIPT_NAME, "Purchase Order", CLIENT_SCRIPT)
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
	_ensure_property_setter("status", "in_list_view", "1", "Check")


def _ensure_property_setter(fieldname, property_name, value, property_type):
	filters = {
		"doc_type": "Purchase Order",
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
	make_property_setter("Purchase Order", fieldname, property_name, value, property_type)


def _save(doc):
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
