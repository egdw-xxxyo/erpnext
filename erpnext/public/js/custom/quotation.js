// «Угода»: what is left to order, and a visible lock while the Workflow runs.
const QUOTATION_DRAFT_STATE = "Опрацьовується";

frappe.ui.form.on("Quotation", {
	refresh: function (frm) {
		render_fulfilment(frm);
		toggle_lock_banner(frm);
	},
});

function toggle_lock_banner(frm) {
	const state = frm.doc.workflow_state;
	if (!state || state === QUOTATION_DRAFT_STATE || frm.is_new()) {
		return;
	}

	frm.dashboard.clear_headline();
	frm.dashboard.set_headline(
		__("The Quotation is being approved and cannot be edited. Return it for rework to change the terms.")
	);
}

function render_fulfilment(frm) {
	const wrapper = frm.get_field("fulfilment_html");
	if (!wrapper) return;

	if (frm.is_new() || frm.doc.docstatus === 0) {
		wrapper.$wrapper.empty();
		return;
	}

	frappe.call({
		method: "erpnext.selling.quotation_rules.get_fulfilment_summary",
		args: { quotation: frm.doc.name },
		callback: function (r) {
			if (!r.message) return;
			wrapper.$wrapper.html(fulfilment_html(r.message));
		},
	});
}

function fulfilment_html(summary) {
	const item_rows = (summary.items || [])
		.map(
			(row) => `
			<tr>
				<td>${frappe.utils.escape_html(row.item_name || row.item_code)}</td>
				<td class="text-right">${format_number(row.qty)}</td>
				<td class="text-right">${format_number(row.ordered_qty)}</td>
				<td class="text-right">${format_number(row.remaining_qty)}</td>
			</tr>`
		)
		.join("");

	const orders = Object.entries(summary.sales_orders || {})
		.map(
			([name, entry]) => `
			<tr>
				<td>${frappe.utils.get_form_link("Sales Order", name, true)}</td>
				<td>${__(entry.status || "")}</td>
				<td class="text-right">${format_number(entry.qty)}</td>
			</tr>`
		)
		.join("");

	return `
		<div class="table-responsive">
			<table class="table table-bordered small">
				<thead>
					<tr>
						<th>${__("Item")}</th>
						<th class="text-right">${__("Approved Quantity")}</th>
						<th class="text-right">${__("Ordered Quantity")}</th>
						<th class="text-right">${__("Remaining Quantity")}</th>
					</tr>
				</thead>
				<tbody>${item_rows}</tbody>
			</table>
		</div>
		${
			orders
				? `<div class="table-responsive">
			<table class="table table-bordered small">
				<thead>
					<tr>
						<th>${__("Sales Order")}</th>
						<th>${__("Status")}</th>
						<th class="text-right">${__("Ordered Quantity")}</th>
					</tr>
				</thead>
				<tbody>${orders}</tbody>
			</table>
		</div>`
				: ""
		}
	`;
}
