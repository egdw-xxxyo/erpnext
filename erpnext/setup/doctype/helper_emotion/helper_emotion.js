frappe.ui.form.on("Helper Emotion", {
	refresh(frm) {
		if (!frm.is_new() && frm.has_perm("write")) {
			frm.add_custom_button(__("Replace Mascot Image"), () => frm.get_field("image").on_attach_click());
		}
	},
});
