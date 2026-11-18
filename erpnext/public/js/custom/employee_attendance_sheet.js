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

		show_attendance_sheet(frm);
	},
});

// Табель працівника прямо на картці: той самий календар, що й у зарплатних документах, —
// відкривається на поточному місяці й гортається стрілками. Числа місяця лишаються в
// документах: на картці немає рядка, з якого їх брати.
function show_attendance_sheet(frm) {
	// календар стоїть на вкладці «Облік робочого часу» (поле `custom_attendance_sheet_html`)
	const field = frm.get_field("custom_attendance_sheet_html");
	if (!field) return;

	if (frm.is_new() || !frappe.model.can_read("Attendance")) {
		frm.toggle_display("custom_attendance_sheet_section", false);
		return;
	}

	const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
	const start = frappe.datetime.obj_to_str(new Date(today.getFullYear(), today.getMonth(), 1));
	const end = frappe.datetime.obj_to_str(new Date(today.getFullYear(), today.getMonth() + 1, 0));
	const row = { employee: frm.doc.name, employee_name: frm.doc.employee_name };
	const settings = { start, end, calendar_slot: true, skip_attendance_table: true, skip_salary: true };
	field.$wrapper.html(erpnext.utils.attendance_details.html(row, settings));

	// календар шукає своє місце в `$wrapper` — діалогу тут немає, його роль грає поле
	erpnext.utils.attendance_details.mount_calendar({ $wrapper: field.$wrapper }, row, settings);
}
