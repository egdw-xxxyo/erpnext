// The "what does this recipe consume" table, shared by the Consumption Recipe form and every
// document that points at a recipe (Packing Template today).
//
//   erpnext.consumption.render(wrapper, {values, rows})
//   erpnext.consumption.show(wrapper, {recipe | items, values, highlight})
//
// `values` are the quantities to try; `highlight` marks one of them (the full box).
frappe.provide("erpnext.consumption");

erpnext.consumption.render = function (wrapper, result, highlight) {
	const esc = frappe.utils.escape_html;
	const head = result.values
		.map((v) => `<th class="text-right${v == highlight ? " bg-light" : ""}">${v}</th>`)
		.join("");
	const body = result.rows
		.map((row) => {
			const cells = result.values
				.map(
					(v) =>
						`<td class="text-right${v == highlight ? " bg-light" : ""}">${row.qty[v] || "—"}</td>`
				)
				.join("");
			const name = row.item_name && row.item_name !== row.item_code ? ` — ${esc(row.item_name)}` : "";
			return `<tr><td>${esc(row.item_code)}${name}</td><td>${esc(row.uom || "")}</td>${cells}</tr>`;
		})
		.join("");
	wrapper.html(
		`<table class="table table-bordered table-sm">
			<thead><tr><th>${__("Item")}</th><th>${__("UOM")}</th>${head}</tr></thead>
			<tbody>${body}</tbody>
		</table>`
	);
};

erpnext.consumption.show = function (wrapper, opts) {
	const args = opts.recipe
		? { recipe: opts.recipe, values: opts.values }
		: { items: opts.items, values: opts.values };
	frappe.call({
		method: opts.recipe
			? "erpnext.manufacturing.consumption.preview_recipe"
			: "erpnext.manufacturing.consumption.preview",
		args: args,
		callback: (r) => {
			erpnext.consumption.render(wrapper, r.message || { values: [], rows: [] }, opts.highlight);
		},
	});
};
