frappe.ui.form.on("Lead", {
	setup: function (frm) {
		frm.set_query("utm_source", () => ({
			query: "erpnext.crm.lead_rules.engagement_channel_query",
		}));

		frm.set_query("utm_medium", () => ({
			query: "erpnext.crm.lead_rules.engagement_channel_detail_query",
			filters: frm.doc.utm_source ? { engagement_channel: frm.doc.utm_source } : {},
		}));
	},

	refresh: function (frm) {
		render_expenses(frm);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Lead Expense"), () => new_expense(frm), __("Create"));
		}
	},

	utm_source: function (frm) {
		if (!frm.doc.utm_medium) return;

		frappe.db.get_value("UTM Medium", frm.doc.utm_medium, "engagement_channel").then(({ message }) => {
			if (message?.engagement_channel && message.engagement_channel !== frm.doc.utm_source) {
				frm.set_value("utm_medium", null);
			}
		});
	},
});

function new_expense(frm) {
	frappe.new_doc("Lead Expense", { lead: frm.doc.name });
}

function render_expenses(frm) {
	const wrapper = frm.get_field("expenses_html")?.$wrapper;
	if (!wrapper) return;

	if (frm.is_new()) {
		wrapper.html(`<p class="text-muted">${__("Save the Lead to add expenses.")}</p>`);
		return;
	}

	frappe.call({
		method: "erpnext.crm.doctype.lead_expense.lead_expense.get_lead_expenses",
		args: { lead: frm.doc.name },
		callback: ({ message }) => {
			if (!message) return;
			wrapper.html(expenses_html(message));
			wrapper.find(".btn-add-expense").on("click", () => new_expense(frm));
		},
	});
}

function expenses_html({ materials, money }) {
	return `
		<div class="mb-3">
			<button class="btn btn-sm btn-primary btn-add-expense">${__("Add Expense")}</button>
		</div>
		<h5>${__("Materials")}</h5>
		${materials.length ? materials_table(materials) : empty_note()}
		<h5 class="mt-4">${__("Money")}</h5>
		${money.length ? money_table(money) : empty_note()}
	`;
}

function empty_note() {
	return `<p class="text-muted">${__("No expenses yet")}</p>`;
}

function expense_link(expense) {
	return frappe.utils.get_form_link("Lead Expense", expense.name, true, __(expense.expense_type));
}

function stock_entry_cell(entries) {
	const readable = frappe.model.can_read("Stock Entry");
	return entries
		.map(
			(entry) =>
				`${
					readable
						? frappe.utils.get_form_link("Stock Entry", entry.name, true)
						: frappe.utils.escape_html(entry.name)
				} — ${entry.docstatus === 1 ? __("Submitted") : __("Draft")}`
		)
		.join("<br>");
}

function item_line(item) {
	return `${frappe.utils.escape_html(item.item_name || item.item_code)} — ${format_number(
		item.issued_qty
	)} / ${format_number(item.qty)} ${frappe.utils.escape_html(item.uom || "")}`;
}

function expense_state(expense) {
	return expense.docstatus === 0 ? __("Not Submitted") : __(expense.stock_entry_status || "");
}

function materials_table(rows) {
	const body = rows
		.map(
			(expense) => `
			<tr>
				<td>${frappe.datetime.str_to_user(expense.expense_date)}</td>
				<td>${expense_link(expense)}</td>
				<td>${expense.items.map(item_line).join("<br>")}</td>
				<td>${stock_entry_cell(expense.stock_entries)}</td>
				<td>${expense_state(expense)}</td>
			</tr>`
		)
		.join("");

	return `
		<div class="table-responsive">
			<table class="table table-bordered small">
				<thead>
					<tr>
						<th>${__("Date")}</th>
						<th>${__("Expense Type")}</th>
						<th>${__("Items")} (${__("Issued / Required")})</th>
						<th>${__("Stock Entry")}</th>
						<th>${__("Stock Entry Status")}</th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		</div>`;
}

function money_table(rows) {
	const body = rows
		.map(
			(expense) => `
			<tr>
				<td>${frappe.datetime.str_to_user(expense.expense_date)}</td>
				<td>${expense_link(expense)}</td>
				<td class="text-right">${format_currency(expense.amount, expense.currency)}</td>
				<td>${frappe.utils.escape_html(expense.description || "")}</td>
				<td>${expense.docstatus === 0 ? __("Not Submitted") : ""}</td>
			</tr>`
		)
		.join("");

	return `
		<div class="table-responsive">
			<table class="table table-bordered small">
				<thead>
					<tr>
						<th>${__("Date")}</th>
						<th>${__("Expense Type")}</th>
						<th class="text-right">${__("Amount")}</th>
						<th>${__("Description")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		</div>`;
}
