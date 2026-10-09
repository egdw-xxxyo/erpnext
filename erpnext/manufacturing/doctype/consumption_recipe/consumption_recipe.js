frappe.ui.form.on("Consumption Recipe", {
	refresh(frm) {
		if (!frm.is_new() && (frm.doc.items || []).length) {
			frm.trigger("calculate");
		}
	},

	calculate(frm) {
		const wrapper = frm.fields_dict.preview_html.$wrapper;
		const items = (frm.doc.items || []).filter((row) => row.item_code);
		if (!items.length) {
			wrapper.html("");
			return;
		}

		frappe.call({
			method: "erpnext.manufacturing.consumption.preview",
			args: { items: items, values: frm.doc.preview_values || "1" },
			callback: (r) => {
				const result = r.message || { values: [], rows: [] };
				const esc = frappe.utils.escape_html;
				const head = result.values.map((v) => `<th class="text-right">${v}</th>`).join("");
				const body = result.rows
					.map((row) => {
						const cells = result.values
							.map((v) => `<td class="text-right">${row.qty[v] || "—"}</td>`)
							.join("");
						const name =
							row.item_name && row.item_name !== row.item_code
								? ` — ${esc(row.item_name)}`
								: "";
						return `<tr><td>${esc(row.item_code)}${name}</td><td>${esc(
							row.uom || ""
						)}</td>${cells}</tr>`;
					})
					.join("");
				wrapper.html(
					`<table class="table table-bordered table-sm">
						<thead><tr><th>${__("Item")}</th><th>${__("UOM")}</th>${head}</tr></thead>
						<tbody>${body}</tbody>
					</table>`
				);
			},
		});
	},
});
