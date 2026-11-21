frappe.ui.form.on("User", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role("Access Manager")) return;
		frm.add_custom_button(
			__("Company Access"),
			() =>
				frappe.db
					.exists("User Company Access", frm.doc.name)
					.then((exists) =>
						exists
							? frappe.set_route("Form", "User Company Access", frm.doc.name)
							: frappe.new_doc("User Company Access", { user: frm.doc.name })
					),
			__("Permissions")
		);
	},
});
