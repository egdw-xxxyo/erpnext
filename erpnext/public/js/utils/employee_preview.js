// Employees of a payroll document read as departments, not as one long grid: the desk
// prototypes grouped them under a department heading with a name search on top, and the
// accountants read the month that way. The grid stays underneath and keeps the editing —
// a click on a name opens its row.

frappe.provide("erpnext.utils.employee_preview");

function render(frm, options) {
	const field = frm.get_field(options.field);
	if (!field) return;

	const rows = frm.doc[options.table] || [];

	if (!rows.length) {
		field.$wrapper.html(
			`<div class="text-muted" style="padding: 12px;">${__("No employees loaded yet.")}</div>`
		);
		return;
	}

	const search = (frm[`__preview_search_${options.field}`] || "").trim().toLowerCase();
	const filtered = frm[`__preview_filter_${options.field}`] && options.filter;
	let visible = search ? rows.filter((row) => search_text(row).includes(search)) : rows;

	if (filtered) visible = visible.filter(options.filter.test);

	// money is hidden until somebody asks for a single employee: the sheet is read over
	// somebody's shoulder, and the whole department's pay does not belong on that screen
	const revealed = frm[`__preview_revealed_${options.field}`] || {};

	field.$wrapper.html(`
		${styles()}
		${search_html(search, options, filtered)}
		${visible.length ? groups_html(visible, options, revealed) : empty_html()}
	`);

	bind(frm, field.$wrapper, options);
}

function search_text(row) {
	return [row.employee_name, row.employee, row.department].filter(Boolean).join(" ").toLowerCase();
}

function search_html(search, options, filtered) {
	return `
		<div class="employee-preview-toolbar">
			<input type="search" class="form-control input-sm employee-preview-search"
				placeholder="${__("Search by name")}" value="${frappe.utils.escape_html(search)}">
			${
				options.filter
					? `<label class="employee-preview-filter">
							<input type="checkbox" class="employee-preview-filter-input"
								${filtered ? "checked" : ""}> ${options.filter.label}
						</label>`
					: ""
			}
		</div>
	`;
}

function empty_html() {
	return `<div class="text-muted" style="padding: 12px;">${__("No employee matches this search.")}</div>`;
}

function groups_html(rows, options, revealed) {
	const groups = {};

	rows.forEach((row) => {
		const group = options.group_by(row);
		(groups[group] = groups[group] || []).push(row);
	});

	return `
		<div class="employee-preview">
			${Object.keys(groups)
				.sort()
				.map((group) => group_html(group, groups[group], options, revealed))
				.join("")}
		</div>
	`;
}

function group_html(group, rows, options, revealed) {
	return `
		<div class="employee-preview-group">
			<div class="employee-preview-title">${frappe.utils.escape_html(group)}</div>
			<table class="table table-bordered employee-preview-table">
				<thead>
					<tr>
						<th>${__("Employee")}</th>
						${options.status_column ? `<th>${options.status_column}</th>` : ""}
						${options.columns.map((column) => `<th class="text-right">${column.label}</th>`).join("")}
						${has_secret(options) ? "<th></th>" : ""}
					</tr>
				</thead>
				<tbody>
					${rows.map((row) => row_html(row, options, revealed)).join("")}
				</tbody>
			</table>
		</div>
	`;
}

function row_html(row, options, revealed) {
	const warn = options.warn && options.warn(row);
	const shown = Boolean(revealed && revealed[cint(row.idx)]);

	return `
		<tr class="${warn ? "employee-preview-warn" : ""}">
			<td>
				<button type="button" class="btn btn-link btn-xs employee-preview-open"
					data-row="${frappe.utils.escape_html(row.name || "")}"
					data-idx="${frappe.utils.escape_html(String(row.idx || ""))}">
					${frappe.utils.escape_html(row.employee_name || row.employee || "")}
				</button>
				${options.name_suffix ? options.name_suffix(row) : ""}
			</td>
			${
				options.status_column
					? `<td>${
							warn
								? `<span class="employee-preview-badge warn">${options.warn_label}</span>`
								: `<span class="employee-preview-badge ok">${options.ok_label}</span>`
					  }</td>`
					: ""
			}
			${options.columns.map((column, index) => cell_html(row, column, index, shown)).join("")}
			${has_secret(options) ? reveal_cell_html(row, shown) : ""}
		</tr>
	`;
}

function has_secret(options) {
	return options.columns.some((column) => column.secret);
}

// the eye of the row: one employee at a time, and the same button puts the money back
function reveal_cell_html(row, shown) {
	return `
		<td class="text-right">
			<button type="button" class="btn btn-link btn-xs employee-preview-reveal"
				data-idx="${frappe.utils.escape_html(String(row.idx || ""))}"
				title="${shown ? __("Hide salary") : __("Show salary")}">
				<i class="fa ${shown ? "fa-eye-slash" : "fa-eye"}"></i>
			</button>
		</td>
	`;
}

function cell_html(row, column, index, shown) {
	if (column.secret && !shown) {
		return `<td class="text-right employee-preview-hidden">•••</td>`;
	}

	const value = column.bold ? `<b>${column.value(row)}</b>` : column.value(row);
	const clickable = column.click && (!column.clickable || column.clickable(row));

	// a column may explain itself in a dialog instead of squeezing everything into the cell
	const content = clickable
		? `<button type="button" class="btn btn-link btn-xs employee-preview-cell"
				data-column="${index}" data-idx="${frappe.utils.escape_html(String(row.idx || ""))}">
				${value}
			</button>`
		: value;

	return `<td class="text-right">${content}</td>`;
}

function bind(frm, $wrapper, options) {
	$wrapper.find(".employee-preview-search").on("input", function () {
		frm[`__preview_search_${options.field}`] = $(this).val() || "";
		// every new search — and clearing it — puts the money back out of sight
		frm[`__preview_revealed_${options.field}`] = {};

		const cursor = this.selectionStart;

		render(frm, options);

		const $input = frm.get_field(options.field).$wrapper.find(".employee-preview-search").first();
		const input = $input.get(0);

		if (input) {
			input.focus();
			input.setSelectionRange && input.setSelectionRange(cursor, cursor);
		}
	});

	$wrapper.find(".employee-preview-filter-input").on("change", function () {
		frm[`__preview_filter_${options.field}`] = this.checked;
		render(frm, options);
	});

	$wrapper.find(".employee-preview-cell").on("click", function () {
		const column = options.columns[cint($(this).attr("data-column"))];
		const row = (frm.doc[options.table] || []).find(
			(item) => cint(item.idx) === cint($(this).attr("data-idx"))
		);

		if (column && column.click && row) column.click(row);
	});

	$wrapper.find(".employee-preview-reveal").on("click", function () {
		const idx = cint($(this).attr("data-idx"));
		const revealed = frm[`__preview_revealed_${options.field}`] || {};

		// only the asked-for employee is open at a time
		frm[`__preview_revealed_${options.field}`] = revealed[idx] ? {} : { [idx]: true };
		render(frm, options);
	});

	$wrapper.find(".employee-preview-open").on("click", function () {
		open_row(frm, options.table, $(this).attr("data-row"), $(this).attr("data-idx"));
	});
}

function open_row(frm, table, name, idx) {
	const grid = frm.fields_dict[table] && frm.fields_dict[table].grid;
	if (!grid) return;

	// the preview lists everybody, the grid shows 50 rows a page: land on the right page first,
	// otherwise the row a click asks for simply is not rendered
	const pagination = grid.grid_pagination;

	if (pagination && cint(idx) && cint(pagination.page_length)) {
		const page = Math.ceil(cint(idx) / cint(pagination.page_length));

		if (page && page !== cint(pagination.page_index)) {
			pagination.go_to_page(page);
		}
	}

	const row =
		(grid.grid_rows_by_docname && grid.grid_rows_by_docname[name]) ||
		(grid.grid_rows || []).find((item) => item.doc && cint(item.doc.idx) === cint(idx));

	if (!row) {
		frappe.msgprint(__("The row of this employee is not on the current page of the table."));
		return;
	}

	row.toggle_view(true);
	frappe.utils.scroll_to(row.wrapper);
}

function money(value) {
	return format_currency(flt(value), frappe.defaults.get_default("currency"));
}

function number(value) {
	const rounded = Math.round(flt(value) * 100) / 100;

	return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

function styles() {
	return `
		<style>
			.employee-preview { display: grid; gap: 14px; }
			.employee-preview-toolbar {
				margin-bottom: 10px;
				display: flex;
				gap: 12px;
				align-items: center;
			}
			.employee-preview-toolbar .employee-preview-search { max-width: 360px; }
			.employee-preview-filter { margin: 0; font-weight: normal; white-space: nowrap; }
			.employee-preview-title {
				padding: 8px 10px;
				background: var(--fg-color, #f8f9fa);
				border: 1px solid var(--border-color, #ddd);
				border-bottom: 0;
				font-weight: 700;
			}
			.employee-preview-table { margin: 0; }
			.employee-preview-table th,
			.employee-preview-table td { padding: 6px 7px; font-size: 12px; vertical-align: middle; }
			.employee-preview-open { padding: 0; border: 0; text-align: left; white-space: normal; }
			.employee-preview-cell { padding: 0; border: 0; }
			.employee-preview-reveal { padding: 0; border: 0; color: var(--text-muted, #8d99a6); }
			.employee-preview-hidden { color: var(--text-muted, #8d99a6); letter-spacing: 2px; }
			.employee-preview-warn td { background: var(--yellow-50, #fff7e6); }
			.employee-preview-badge {
				display: inline-block;
				padding: 2px 6px;
				border-radius: 4px;
				font-size: 11px;
				line-height: 1.3;
			}
			.employee-preview-badge.warn { background: var(--yellow-100, #ffe8b3); color: var(--yellow-700, #8a5a00); }
			.employee-preview-badge.ok { background: var(--green-100, #e8f5e9); color: var(--green-700, #1b6b2a); }
		</style>
	`;
}

Object.assign(erpnext.utils.employee_preview, { render, money, number });
