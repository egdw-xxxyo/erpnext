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
			__("Vacation"),
			`${__("{0} d", [number(row.vacation_days)])} (${__("paid by the Vacation Pay Sheet")})`,
		]);
	}

	if (flt(row.sick_calendar_days)) {
		const cases = (row.sick_cases || "")
			.split(/\s+/)
			.filter(Boolean)
			.map(
				(name) =>
					`<a href="/desk/sick-leave-case/${encodeURIComponent(name)}">${frappe.utils.escape_html(
						name
					)}</a>`
			)
			.join(", ");

		lines.push([
			__("Sick Pay (Employer)"),
			`${money(row.sick_pay)} (${__("{0} d", [number(row.sick_calendar_days)])}, ${money(
				row.sick_average
			)} × ${number(row.sick_percent)}%)${cases ? `<br><small>${cases}</small>` : ""}`,
		]);
	}

	if (flt(row.sick_pay_fund)) {
		lines.push([
			__("Sick Pay (Fund)"),
			`<span class="text-muted">${money(row.sick_pay_fund)} (${__(
				"paid separately by the sick leave case"
			)})</span>`,
		]);
	}

	return lines;
};
