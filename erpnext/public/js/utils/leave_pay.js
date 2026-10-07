frappe.provide("erpnext.utils.leave_pay");

// Рядки відпускних і лікарняних для попапів зарплатних документів. Обидві виплати рахуються
// за середньоденною зарплатою і за календарні дні (див. `erpnext.hr.average_pay`), тож у
// розкладі вони стоять окремо від окладу за відпрацьовані дні.
erpnext.utils.leave_pay.lines = function (row) {
	const money = (value) => erpnext.utils.employee_preview.money(value);
	const number = (value) => erpnext.utils.employee_preview.number(value);
	const lines = [];

	if (!flt(row.vacation_days) && !flt(row.sick_calendar_days)) return lines;

	lines.push([__("Days Paid by Salary"), number(row.official_days)]);

	if (flt(row.vacation_days)) {
		lines.push([
			__("Vacation Pay"),
			`${money(row.vacation_pay)} (${__("{0} d", [number(row.vacation_days)])} × ${money(
				row.vacation_average
			)})`,
		]);
	}

	if (flt(row.sick_calendar_days)) {
		lines.push([
			__("Sick Pay (Employer)"),
			`${money(row.sick_pay)} (${money(row.sick_average)} × ${number(row.sick_percent)}%)`,
		]);
	}

	if (flt(row.sick_pay_fund)) {
		lines.push([
			__("Sick Pay (Pension Fund)"),
			`<span class="text-muted">${money(row.sick_pay_fund)}</span>`,
		]);
	}

	return lines;
};
