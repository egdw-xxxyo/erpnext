frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (
			frm.doc.docstatus !== 1 ||
			!frappe.user_roles.includes("System Manager") ||
			["Closed", "On Hold"].includes(frm.doc.status)
		)
			return;
		frm.add_custom_button(
			__("Link existing purchase receipts"),
			async () => {
				const response = await frappe.call({
					method: "erpnext.buying.procurement_receipt_linking.get_candidates",
					args: { order_name: frm.doc.name },
					freeze: true,
				});
				const result = response.message || {};
				if (!result.rows?.length) {
					frappe.msgprint(__("No matching unlinked purchase receipts found."));
					return;
				}
				const labels = Object.fromEntries(
					result.order_rows.map((row) => [
						row.name,
						`${row.idx}: ${row.item_name} (${row.qty} ${row.uom})`,
					])
				);
				const data = result.rows.map((row, index) => ({
					...row,
					candidate: index,
					order_row: row.matches.length === 1 ? labels[row.matches[0]] : "",
				}));
				let dialog;
				dialog = new frappe.ui.Dialog({
					title: __("Link existing purchase receipts"),
					size: "extra-large",
					fields: [
						{
							fieldtype: "HTML",
							options: `<div class="alert alert-info">${__(
								"Select rows from one or several receipts. Only references will change; stock will not be received again."
							)}</div>`,
						},
						{
							fieldname: "rows",
							fieldtype: "Table",
							label: __("Purchase Receipts"),
							cannot_add_rows: true,
							cannot_delete_rows: true,
							data,
							fields: [
								{
									fieldname: "use",
									fieldtype: "Check",
									label: __("Link"),
									in_list_view: 1,
									onchange: () => render_receipt_coverage(dialog, result, labels),
								},
								{
									fieldname: "receipt",
									fieldtype: "Link",
									options: "Purchase Receipt",
									label: __("Purchase Receipt"),
									read_only: 1,
									in_list_view: 1,
								},
								{
									fieldname: "item_name",
									fieldtype: "Data",
									label: __("Item"),
									read_only: 1,
									in_list_view: 1,
								},
								{
									fieldname: "description",
									fieldtype: "Small Text",
									label: __("Description"),
									read_only: 1,
								},
								{
									fieldname: "qty",
									fieldtype: "Float",
									label: __("Quantity"),
									read_only: 1,
									in_list_view: 1,
								},
								{
									fieldname: "order_row",
									fieldtype: "Select",
									label: __("Order row"),
									options: ["", ...Object.values(labels)].join("\n"),
									in_list_view: 1,
									onchange: () => render_receipt_coverage(dialog, result, labels),
								},
								{ fieldname: "candidate", fieldtype: "Int", hidden: 1 },
							],
						},
						{ fieldname: "coverage", fieldtype: "HTML" },
					],
					primary_action_label: __("Link"),
					primary_action(values) {
						const selected = (values.rows || []).filter((row) => row.use);
						if (!selected.length) {
							frappe.msgprint(__("Select receipt rows to link."));
							return;
						}
						const mappings = selected.map((row) => {
							const source = result.rows[row.candidate];
							return {
								receipt: source.receipt,
								receipt_row: source.receipt_row,
								order_row: Object.keys(labels).find((key) => labels[key] === row.order_row),
							};
						});
						if (mappings.some((row) => !row.order_row)) {
							frappe.msgprint(__("Select an order row for each receipt row."));
							return;
						}
						frappe.confirm(__("Link the selected receipt rows to this order?"), async () => {
							await frappe.call({
								method: "erpnext.buying.procurement_receipt_linking.link_receipts",
								args: { order_name: frm.doc.name, mappings },
								freeze: true,
							});
							dialog.hide();
							await frm.reload_doc();
						});
					},
				});
				dialog.show();
				render_receipt_coverage(dialog, result, labels);
			},
			__("Actions")
		);
	},
});

function render_receipt_coverage(dialog, result, labels) {
	if (!dialog) return;
	const selected = (dialog.get_values()?.rows || []).filter((row) => row.use);
	const totals = {};
	for (const row of selected) {
		const key = Object.keys(labels).find((key) => labels[key] === row.order_row);
		if (key) totals[key] = (totals[key] || 0) + flt(row.qty);
	}
	const body = result.order_rows
		.map(
			(row) =>
				`<li class="${
					(totals[row.name] || 0) > row.qty ? "text-danger" : ""
				}">${frappe.utils.escape_html(row.item_name)}: ${totals[row.name] || 0} / ${
					row.qty
				} ${frappe.utils.escape_html(row.uom)}</li>`
		)
		.join("");
	dialog
		.get_field("coverage")
		.$wrapper.html(`<strong>${__("Coverage by order row")}</strong><ul>${body}</ul>`);
}
