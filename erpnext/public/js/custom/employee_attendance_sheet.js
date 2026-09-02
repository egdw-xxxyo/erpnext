// Додаткові працівники в табелі — керівник веде їх понад своїх прямих підлеглих.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		// Table MultiSelect reads get_query off the parent field, not off the link
		// inside the child table, so the query is set on the field itself.
		frm.set_query("attendance_sheet_extra_employees", function (doc) {
			return {
				query: "erpnext.payroll_ua.page.attendance_sheet.attendance_sheet.extra_employee_query",
				filters: { manager: doc.name },
			};
		});
	},
});
