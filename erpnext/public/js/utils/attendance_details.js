frappe.provide("erpnext.utils.attendance_details");

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);
const hours = (value) => __("{0} h", [number(value)]);
const days = (value) => __("{0} d", [number(value)]);

function attendance_lines(row) {
	return [
		[__("Present Days"), number(row.present_days)],
		[__("Half Days"), number(row.half_days)],
		[__("Sick Leave Days"), number(row.sick_days)],
		[__("Paid Leave Days"), number(row.leave_days)],
		[__("Unpaid Leave Days"), number(row.unpaid_leave_days)],
		[__("Absent Days"), number(row.absent_days)],
		[__("Overtime Hours"), hours(row.overtime_hours)],
		[__("Shortfall Hours"), hours(row.shortfall_hours)],
		[__("Credited Days"), `<b>${days(row.credited_days)} / ${hours(row.working_hours)}</b>`],
	];
}

function table_html(lines) {
	return `
		<table class="table table-bordered attendance-details-table">
			<tbody>
				${lines.map(([label, value]) => `<tr><td>${label}</td><td class="text-right">${value}</td></tr>`).join("")}
			</tbody>
		</table>
	`;
}

function section_html(title, body) {
	return `
		<div class="attendance-details-section">
			<div class="attendance-details-heading">${title}</div>
			${body}
		</div>
	`;
}

function note_html(note) {
	return note ? `<p class="text-muted attendance-details-note">${frappe.utils.escape_html(note)}</p>` : "";
}

function html(row, options) {
	const settings = options || {};
	const calendar = settings.calendar_slot
		? `<div class="attendance-details-calendar" data-calendar="1">${loading_html()}</div>`
		: "";

	return `
		${styles()}
		<div class="attendance-details">
			${section_html(
				__("Attendance"),
				`${calendar}${table_html(attendance_lines(row).concat(settings.attendance || []))}`
			)}
			${section_html(__("Salary"), table_html(settings.salary || []))}
			${note_html(settings.note)}
		</div>
	`;
}

function loading_html() {
	return `<div class="text-muted attendance-details-loading">${__("Loading the month...")}</div>`;
}

function show(row, options) {
	const settings = options || {};
	const dialog = frappe.msgprint({
		title: settings.title || row.employee_name || row.employee,
		indicator: settings.indicator || "blue",
		message: html(row, Object.assign({}, settings, { calendar_slot: true })),
	});

	load_calendar(dialog, row, settings);

	return dialog;
}

function load_calendar(dialog, row, settings) {
	const slot = () => $(dialog.$wrapper).find("[data-calendar]");

	if (!row.employee || !settings.start || !settings.end) {
		slot().remove();
		return;
	}

	frappe
		.call({
			method: "erpnext.hr.salary_advance.attendance_calendar",
			args: { employee: row.employee, start: settings.start, end: settings.end },
		})
		.then((response) => {
			const data = response && response.message;

			if (!data) {
				slot().remove();
				return;
			}

			slot().html(calendar_html(data));
		})
		.catch(() => slot().remove());
}

function calendar_html(data) {
	const start = frappe.datetime.str_to_obj(data.start);
	const end = frappe.datetime.str_to_obj(data.end);
	const months = month_starts(start, end);

	return `
		<div class="attendance-calendar">
			${months.map((month) => month_html(month, data, start, end)).join("")}
			${legend_html(data)}
		</div>
	`;
}

function month_starts(start, end) {
	const months = [];
	const cursor = new Date(start.getFullYear(), start.getMonth(), 1);

	while (cursor <= end) {
		months.push(new Date(cursor));
		cursor.setMonth(cursor.getMonth() + 1);
	}

	return months;
}

function month_html(month, data, start, end) {
	const first = new Date(month.getFullYear(), month.getMonth(), 1);
	const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
	const lead = (first.getDay() + 6) % 7;
	const cells = [];

	for (let index = 0; index < lead; index++) {
		cells.push(`<div class="attendance-calendar-cell blank"></div>`);
	}

	for (let day = 1; day <= last.getDate(); day++) {
		cells.push(day_html(new Date(month.getFullYear(), month.getMonth(), day), data, start, end));
	}

	return `
		<div class="attendance-calendar-month">
			<div class="attendance-calendar-title">${month_label(month)}</div>
			<div class="attendance-calendar-grid">
				${weekday_html(data)}
				${cells.join("")}
			</div>
		</div>
	`;
}

function month_label(month) {
	return frappe.format(frappe.datetime.obj_to_str(month), { fieldtype: "Date" }).replace(/^\S+\s/, "");
}

function weekday_html(data) {
	return (data.weekdays || [])
		.map((name) => `<div class="attendance-calendar-weekday">${name}</div>`)
		.join("");
}

function day_html(date, data, start, end) {
	const key = frappe.datetime.obj_to_str(date);
	const outside = date < start || date > end;
	const entry = data.days[key];
	const note = entry && entry.note;

	return `
		<div class="attendance-calendar-cell${outside ? " outside" : ""}"
			style="${entry ? `border-left: 2px solid ${entry.color};` : ""}"
			title="${frappe.utils.escape_html(day_title(date, entry))}">
			<span class="attendance-calendar-day">${date.getDate()}</span>
			${entry ? `<span class="attendance-calendar-mark" style="color: ${entry.color};">${entry.mark}</span>` : ""}
			${note ? `<span class="attendance-calendar-note ${note.kind}">${note.text}</span>` : ""}
		</div>
	`;
}

function day_title(date, entry) {
	const parts = [frappe.format(frappe.datetime.obj_to_str(date), { fieldtype: "Date" })];

	if (entry) {
		parts.push(entry.label);

		if (entry.leave_type) parts.push(entry.leave_type);
		if (entry.unpaid) parts.push(__("Unpaid Leave"));
	}

	return parts.join(" · ");
}

function legend_html(data) {
	return `
		<div class="attendance-calendar-legend">
			${(data.legend || [])
				.map(
					(item) =>
						`<span class="attendance-calendar-legend-item" style="border-left: 2px solid ${item.color};">${item.label} — ${item.mark}</span>`
				)
				.join("")}
		</div>
	`;
}

function styles() {
	return `
		<style>
			.attendance-details-section { margin-bottom: 16px; }
			.attendance-details-section:last-child { margin-bottom: 0; }
			.attendance-details-heading {
				font-weight: 700;
				font-size: 13px;
				margin-bottom: 6px;
				padding-bottom: 4px;
				border-bottom: 1px solid var(--border-color, #ddd);
			}
			.attendance-details-table { margin: 0; }
			.attendance-details-table td { padding: 5px 7px; font-size: 12px; }
			.attendance-details-note { margin-top: 8px; }
			.attendance-details-loading { padding: 8px 0; font-size: 12px; }
			.attendance-details-calendar { margin-bottom: 10px; }
			.attendance-calendar { display: grid; gap: 10px; }
			.attendance-calendar-title { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
			.attendance-calendar-grid {
				display: grid;
				grid-template-columns: repeat(7, 1fr);
				gap: 2px;
			}
			.attendance-calendar-weekday {
				font-size: 10px;
				text-align: center;
				color: var(--text-muted, #8d99a6);
				padding-bottom: 2px;
			}
			.attendance-calendar-cell {
				position: relative;
				min-height: 34px;
				border: 1px solid var(--border-color, #e2e2e2);
				border-radius: 3px;
				padding: 2px 3px;
				font-size: 10px;
				line-height: 1.15;
			}
			.attendance-calendar-cell.blank { border: 0; }
			.attendance-calendar-cell.outside { opacity: 0.35; }
			.attendance-calendar-day { color: var(--text-muted, #8d99a6); }
			.attendance-calendar-mark {
				position: absolute;
				right: 3px;
				top: 2px;
				font-weight: 700;
				font-size: 10px;
			}
			.attendance-calendar-note {
				position: absolute;
				right: 3px;
				bottom: 2px;
				font-size: 9px;
			}
			.attendance-calendar-note.over { color: var(--green-600, #1f8a3b); }
			.attendance-calendar-note.under { color: var(--red-600, #c8372d); }
			.attendance-calendar-note.leave { color: var(--text-muted, #8d99a6); }
			.attendance-calendar-legend {
				display: flex;
				flex-wrap: wrap;
				gap: 10px;
				font-size: 10px;
				color: var(--text-muted, #8d99a6);
			}
			.attendance-calendar-legend-item { padding-left: 5px; margin-right: 3px; }
		</style>
	`;
}

Object.assign(erpnext.utils.attendance_details, { html, show, attendance_lines });
