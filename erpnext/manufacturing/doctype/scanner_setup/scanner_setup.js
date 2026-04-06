frappe.ui.form.on("Scanner Setup", {
	regenerate_api_key: function (frm) {
		if (frm.is_new()) {
			frappe.msgprint(__("Please save the document first."));
			return;
		}
		frappe.confirm(
			__("Are you sure you want to regenerate the API key? The old key will stop working immediately."),
			function () {
				frappe.call({
					method: "erpnext.manufacturing.doctype.scanner_setup.scanner_setup.regenerate_api_key",
					args: { scanner_name: frm.doc.name },
					callback: function (r) {
						if (r.message) {
							frm.set_value("api_key_preview", r.message);
							frm.refresh_fields();
						}
					},
				});
			}
		);
	},
});
