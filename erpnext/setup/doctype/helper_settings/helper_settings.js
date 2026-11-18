frappe.ui.form.on("Helper Settings", {
	manage_emotions() {
		frappe.set_route("List", "Helper Emotion");
	},
});
