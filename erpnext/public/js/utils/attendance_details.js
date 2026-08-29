frappe.provide("erpnext.utils.attendance_details");

const money = (value) => erpnext.utils.employee_preview.money(value);
const number = (value) => erpnext.utils.employee_preview.number(value);
const hours = (value) => __("{0} h", [number(value)]);
const days = (value) => __("{0} d", [number(value)]);

function attendance_lines(row) {
	return [
		[__("Present Days"), number(row.present_days)],
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

	// Числа табеля живуть у рядку документа: там, де їх немає (зміна окладу), лишається
	// сам календар — його сервер віддає по працівнику, а не по рядку.
	const details = settings.skip_attendance_table
		? ""
		: `<details class="attendance-details-accordion">
				<summary>${__("Attendance Details")}</summary>
				${table_html(attendance_lines(row).concat(settings.attendance || []))}
			</details>`;

	// Діалог виплати питає про гроші — табель там лише відсуває кнопку вниз (`skip_attendance`).
	const attendance = settings.skip_attendance
		? ""
		: section_html(__("Attendance"), `${calendar}${details}`);

	return `
		${styles()}
		<div class="attendance-details">
			${attendance}
			${section_html(__("Salary"), table_html(settings.salary || []))}
			${settings.payout ? section_html(__("Taxes and Payout"), table_html(settings.payout)) : ""}
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

	show_month(dialog, row, settings, settings.start, settings.end);
}

// Місяць гортається на місці: попап відкривається на періоді документа, а стрілки просто
// перезапитують інший місяць — так видно, що було в людини раніше, не виходячи з форми.
function show_month(dialog, row, settings, start, end) {
	const slot = () => $(dialog.$wrapper).find("[data-calendar]");

	slot().html(loading_html());

	frappe
		.call({
			method: "erpnext.hr.salary_advance.attendance_calendar",
			args: { employee: row.employee, start, end },
		})
		.then((response) => {
			const data = response && response.message;

			if (!data) {
				slot().remove();
				return;
			}

			slot().html(`${nav_html(start, settings)}${calendar_html(data)}`);
			bind_nav(dialog, row, settings, start);
		})
		.catch(() => slot().remove());
}

// Період документа лишається якорем: до нього завжди можна повернутися одним кліком.
function nav_html(start, settings) {
	const home =
		settings.start &&
		frappe.datetime.obj_to_str(month_start(settings.start)) !==
			frappe.datetime.obj_to_str(month_start(start));

	return `
		<div class="attendance-calendar-nav">
			<button class="btn btn-xs btn-default" data-month="prev">
				<i class="fa fa-chevron-left"></i>
			</button>
			<span class="attendance-calendar-nav-label">${month_label(month_start(start))}</span>
			<button class="btn btn-xs btn-default" data-month="next">
				<i class="fa fa-chevron-right"></i>
			</button>
			${
				home
					? `<button class="btn btn-xs btn-default" data-month="home">${__(
							"Period of the Document"
					  )}</button>`
					: ""
			}
		</div>
	`;
}

function bind_nav(dialog, row, settings, start) {
	$(dialog.$wrapper)
		.find("[data-month]")
		.on("click", function () {
			const step = { prev: -1, next: 1 }[$(this).attr("data-month")];

			if (step === undefined) {
				show_month(dialog, row, settings, settings.start, settings.end);
				return;
			}

			const first = month_start(start);
			const moved = new Date(first.getFullYear(), first.getMonth() + step, 1);
			const last = new Date(moved.getFullYear(), moved.getMonth() + 1, 0);

			show_month(
				dialog,
				row,
				settings,
				frappe.datetime.obj_to_str(moved),
				frappe.datetime.obj_to_str(last)
			);
		});
}

function month_start(date) {
	const parsed = frappe.datetime.str_to_obj(date);

	return new Date(parsed.getFullYear(), parsed.getMonth(), 1);
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
	const entry = data.days[key];
	const note = entry && entry.note;
	const classes = ["attendance-calendar-cell"].concat(day_classes(date, entry, start, end));

	return `
		<div class="${classes.join(" ")}"
			style="${entry && entry.color ? `border-left: 2px solid ${entry.color};` : ""}"
			title="${frappe.utils.escape_html(day_title(date, entry))}">
			<span class="attendance-calendar-day">${date.getDate()}</span>
			${
				entry && entry.mark
					? `<span class="attendance-calendar-mark" style="color: ${entry.color};">${entry.mark}</span>`
					: ""
			}
			${
				entry && entry.boundary
					? `<i class="fa fa-sign-${
							entry.boundary === "joined" ? "in" : "out"
					  } attendance-calendar-boundary"></i>`
					: ""
			}
			${note ? `<span class="attendance-calendar-note ${note.kind}">${note.text}</span>` : ""}
		</div>
	`;
}

// Фон дня — це його ціна: зелений оплачується, червоний ні, свята й дні поза періодом
// роботи лишаються без фону, бо їх ніхто й не мав платити.
function day_classes(date, entry, start, end) {
	const classes = [];

	if (date < start || date > end) classes.push("outside");
	if (!entry) return classes;

	if (entry.outside_employment) classes.push("unemployed");
	if (entry.paid !== undefined && entry.paid !== null) {
		classes.push(entry.paid >= 1 ? "paid" : entry.paid > 0 ? "part-paid" : "unpaid");
	}
	if (entry.boundary) classes.push(entry.boundary);

	return classes;
}

function day_title(date, entry) {
	const parts = [frappe.format(frappe.datetime.obj_to_str(date), { fieldtype: "Date" })];

	if (entry) {
		parts.push(entry.label);

		if (entry.leave_type) parts.push(entry.leave_type);
		if (entry.unpaid) parts.push(__("Unpaid Leave"));
		if (entry.boundary === "joined") parts.push(__("Joined the company"));
		if (entry.boundary === "relieved") parts.push(__("Left the company"));

		if (entry.outside_employment) parts.push(__("Outside the employment period"));
		else if (entry.paid === 0) parts.push(__("Unpaid Day"));
		else if (entry.paid > 0) parts.push(__("Paid Day"));
	}

	return parts.join(" · ");
}

function legend_html(data) {
	const statuses = (data.legend || []).map(
		(item) =>
			`<span class="attendance-calendar-legend-item" style="border-left: 2px solid ${item.color};">${item.label} — ${item.mark}</span>`
	);
	const extra = [
		`<span class="attendance-calendar-legend-item paid">${__("Paid Day")}</span>`,
		`<span class="attendance-calendar-legend-item unpaid">${__("Unpaid Day")}</span>`,
	];

	if (data.joined_on) {
		extra.push(
			`<span class="attendance-calendar-legend-item"><i class="fa fa-sign-in"></i> ${__(
				"Joined the company"
			)}</span>`
		);
	}

	if (data.relieved_on) {
		extra.push(
			`<span class="attendance-calendar-legend-item"><i class="fa fa-sign-out"></i> ${__(
				"Left the company"
			)}</span>`
		);
	}

	return `<div class="attendance-calendar-legend">${statuses.concat(extra).join("")}</div>`;
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
			.attendance-calendar-cell.unemployed { opacity: 0.45; }
			.attendance-calendar-cell.paid { background-color: rgba(46, 160, 67, 0.14); }
			.attendance-calendar-cell.part-paid { background-color: rgba(46, 160, 67, 0.07); }
			.attendance-calendar-cell.unpaid { background-color: rgba(200, 55, 45, 0.14); }
			.attendance-calendar-cell.joined,
			.attendance-calendar-cell.relieved { box-shadow: inset 0 0 0 1px var(--blue-500, #2490ef); }
			.attendance-calendar-boundary {
				position: absolute;
				left: 3px;
				bottom: 2px;
				font-size: 9px;
				color: var(--blue-500, #2490ef);
			}
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
			.attendance-calendar-legend-item.paid,
			.attendance-calendar-legend-item.unpaid { padding-right: 5px; border-radius: 3px; }
			.attendance-calendar-legend-item.paid { background-color: rgba(46, 160, 67, 0.14); }
			.attendance-calendar-legend-item.unpaid { background-color: rgba(200, 55, 45, 0.14); }
			.attendance-details-accordion > summary {
				cursor: pointer;
				font-size: 12px;
				color: var(--text-muted, #8d99a6);
				padding: 4px 0;
			}
			.attendance-details-accordion[open] > summary { margin-bottom: 4px; }
		</style>
	`;
}

// `load_calendar` віддається назовні: форма може зібрати власний діалог (із полями, а не
// самим текстом) і повісити той самий календар у його розмітку.
Object.assign(erpnext.utils.attendance_details, {
	html,
	show,
	attendance_lines,
	mount_calendar: load_calendar,
});
