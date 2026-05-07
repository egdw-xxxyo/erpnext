// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

async function open_set_values_dialog(frm) {
	const rows = frm.doc.attributes || [];
	if (!rows.length) {
		frappe.msgprint(__("Add attributes first."));
		return;
	}

	const value_lists = await Promise.all(
		rows.map((row) =>
			frappe.call({
				method: "erpnext.stock.doctype.bpak.bpak.get_attribute_values",
				args: { attribute: row.attribute },
			}).then((r) => r.message || [])
		)
	);

	const fields = rows.map((row, i) => ({
		fieldname: `val_${i}`,
		fieldtype: "Select",
		label: row.attribute,
		options: ["", ...value_lists[i]].join("\n"),
		default: row.attribute_value || "",
		reqd: 1,
	}));

	const dialog = new frappe.ui.Dialog({
		title: __("Set Attribute Values"),
		fields,
		primary_action_label: __("Apply"),
		primary_action(values) {
			rows.forEach((row, i) => {
				row.attribute_value = values[`val_${i}`];
			});
			frm.refresh_field("attributes");
			frm.dirty();
			dialog.hide();
		},
	});
	dialog.show();
}

frappe.ui.form.on("BpAK Template", {
	refresh(frm) {
		frm.add_custom_button(__("Set Attribute Values"), () => open_set_values_dialog(frm));
	},
});
