frappe.ui.form.on("Incapacity Case", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.page.set_indicator(__(frm.doc.status), frm.doc.status === "Closed" ? "blue" : "orange");
		frm.add_custom_button(__("New Sick Leave Case"), () => {
			frappe.new_doc("Sick Leave Case", {
				incapacity_case: frm.doc.name,
				employee: frm.doc.employee,
				company: frm.doc.company,
				case_type: frm.doc.case_type,
				start_date: frm.doc.end_date ? frappe.datetime.add_days(frm.doc.end_date, 1) : null,
			});
		});
	},
});
