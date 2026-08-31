// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Military Unit", {
	refresh(frm) {
		if (frm.is_new()) {
			frappe.contacts.clear_address_and_contact(frm);
			return;
		}

		frappe.contacts.render_address_and_contact(frm);

		frm.add_custom_button(__("Contact"), () => create_contact(frm), __("Create"));
		frm.add_custom_button(__("Prospect"), () => create_prospect(frm), __("Create"));
		frm.add_custom_button(__("Customer"), () => create_customer(frm), __("Create"));
	},
});

function create_contact(frm) {
	const contact = frappe.model.get_new_doc("Contact");
	const link = frappe.model.add_child(contact, "links");
	link.link_doctype = "Military Unit";
	link.link_name = frm.doc.name;
	link.link_title = frm.doc.name_of_military_unit;
	frappe.set_route("Form", "Contact", contact.name);
}

function create_prospect(frm) {
	const prospect = frappe.model.get_new_doc("Prospect");
	prospect.company_name = frm.doc.name_of_military_unit || frm.doc.military_unit_code;
	prospect.military_unit = frm.doc.name;
	frappe.set_route("Form", "Prospect", prospect.name);
}

function create_customer(frm) {
	const customer = frappe.model.get_new_doc("Customer");
	customer.customer_name = frm.doc.name_of_military_unit || frm.doc.military_unit_code;
	customer.military_unit = frm.doc.name;
	frappe.set_route("Form", "Customer", customer.name);
}
