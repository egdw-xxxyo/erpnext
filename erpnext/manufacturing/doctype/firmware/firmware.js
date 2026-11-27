frappe.ui.form.on("Firmware", {
	refresh(frm) {
		const field = frm.get_field("versions_html");
		field.$wrapper.empty();
		if (frm.is_new()) return;

		frm.add_custom_button(__("New Version"), () => {
			frappe.new_doc("Firmware Version", { firmware: frm.doc.name });
		});

		frappe.db
			.get_list("Firmware Version", {
				filters: { firmware: frm.doc.name },
				fields: ["name", "version", "status", "released_on", "sha256", "image_size"],
				order_by: "creation desc",
				limit: 100,
			})
			.then((rows) => {
				const esc = frappe.utils.escape_html;
				new erpnext.DataTable({
					parent: field.$wrapper,
					storage_key: "firmware-versions",
					max_height: "360px",
					rows,
					columns: [
						{ key: "version", label: __("Version"), pin: true, html: (r) => esc(r.version) },
						{ key: "status", label: __("Status"), html: (r) => esc(__(r.status)) },
						{
							key: "released_on",
							label: __("Released On"),
							html: (r) => (r.released_on ? frappe.datetime.str_to_user(r.released_on) : ""),
						},
						{ key: "sha256", label: "SHA-256", html: (r) => esc((r.sha256 || "").slice(0, 12)) },
					],
					on_row_click: (r) => frappe.set_route("Form", "Firmware Version", r.name),
				});
			});
	},
});
