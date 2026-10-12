frappe.ui.form.on("Role", {
	refresh(frm) {
		if (frm.is_new() || !erpnext.access_control.can_manage()) return;
		frm.add_custom_button(__("What this role grants"), () =>
			erpnext.access_control.show_role_grants(frm.doc.name)
		);
	},
});
