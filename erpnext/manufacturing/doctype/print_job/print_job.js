frappe.ui.form.on("Print Job", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Queued" || frm.doc.status === "Failed") {
			frm.add_custom_button(__("Print Now"), () => {
				frappe.call({
					method: "erpnext.manufacturing.doctype.label_printer.label_printer.print_label",
					args: { print_job_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Sending to printer..."),
					callback(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({ message: __("Label printed!"), indicator: "green" });
						}
						frm.reload_doc();
					},
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Queued") {
			frm.add_custom_button(__("Cancel"), () => {
				frappe.call({
					method: "erpnext.manufacturing.doctype.label_printer.label_printer.cancel_print_job",
					args: { print_job_name: frm.doc.name },
					callback() {
						frm.reload_doc();
					},
				});
			});
		}
	},
});
