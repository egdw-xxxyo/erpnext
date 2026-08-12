frappe.pages["eskd-bpak-matrix"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Матриця БпАК (борт × НСУ)"),
		single_column: true,
	});

	const product_field = page.add_field({
		label: __("Product"),
		fieldtype: "Link",
		fieldname: "product",
		options: "ESKD Product",
		change: () => render(),
	});

	const $container = $('<div class="bpak-matrix"></div>').appendTo(page.body);

	$("<style>")
		.text(
			`
		.bpak-matrix table { font-size: 13px; }
		.bpak-matrix th.gs-col {
			writing-mode: vertical-rl;
			transform: rotate(180deg);
			vertical-align: bottom;
			text-align: left;
			white-space: nowrap;
			padding: 8px 4px;
			height: 190px;
			min-width: 36px;
			max-width: 36px;
		}
		.bpak-matrix th.gs-col a { color: inherit; text-decoration: none; }
		.bpak-matrix td { vertical-align: middle; text-align: center; }
		.bpak-matrix td.cell-name { text-align: left; }
		.bpak-matrix td.cell-toggle { cursor: pointer; }
		.bpak-matrix td.cell-toggle:hover { background: var(--fg-hover-color); }
		.bpak-matrix td.cell-taken { color: var(--text-on-green, #0f766e); font-weight: 600; }
		.bpak-matrix .free-badge {
			display: inline-block;
			background: var(--bg-light-gray, #f4f5f6);
			border-radius: 8px;
			padding: 0 6px;
			margin-left: 4px;
			font-size: 11px;
			color: var(--text-muted);
		}
	`
		)
		.appendTo("head");

	function spec_link(name, label) {
		const route = `/app/specification/${encodeURIComponent(name)}`;
		return `<a href="${route}">${frappe.utils.escape_html(label || name)}</a>`;
	}

	function render() {
		const product = product_field.get_value();
		if (!product) {
			$container.html(
				`<div class="text-muted" style="margin: 15px 0;">${__("Select a product")}</div>`
			);
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.page.eskd_bpak_matrix.eskd_bpak_matrix.get_matrix",
			args: { product },
			callback: (r) => paint(r.message),
		});
	}

	function paint(data) {
		if (!data) return;
		const columns = data.columns || [];
		const rows = data.rows || [];

		let html = '<table class="table table-bordered">';
		html += "<thead><tr>";
		html += `<th>${__("Board Specification")}</th>`;
		html += `<th>${__("Specification Name")}</th>`;
		for (const column of columns) {
			html += `<th class="gs-col">${spec_link(column.name, column.specification_code)}</th>`;
		}
		html += "</tr></thead><tbody>";

		for (const row of rows) {
			const free = row.free.length
				? `<span class="free-badge" title="${__("Unassigned modifications")}">${
						row.free.length
				  }</span>`
				: "";
			html += "<tr>";
			html += `<td>${spec_link(row.board, row.code)}${free}</td>`;
			html += `<td class="cell-name">${frappe.utils.escape_html(row.name || "")}</td>`;
			for (const column of columns) {
				const cell = row.cells[column.name];
				const attrs = `data-board="${frappe.utils.escape_html(
					row.board
				)}" data-gs="${frappe.utils.escape_html(column.name)}"`;
				if (cell) {
					html += `<td class="cell-toggle cell-taken" ${attrs} data-combination="${frappe.utils.escape_html(
						cell.combination
					)}" title="${__("Click to release")}">${cell.modification_number}</td>`;
				} else {
					html += `<td class="cell-toggle" ${attrs} title="${__(
						"Click to assign a modification"
					)}"></td>`;
				}
			}
			html += "</tr>";
		}
		html += "</tbody></table>";

		if (!rows.length) {
			html += `<div class="text-muted">${__("No modifications for this product")}</div>`;
		}

		$container.html(html);
		$container.find("td.cell-toggle").on("click", on_cell_click);
	}

	function on_cell_click() {
		const $cell = $(this);
		const combination = $cell.attr("data-combination");
		const method = combination
			? "erpnext.manufacturing.page.eskd_bpak_matrix.eskd_bpak_matrix.unassign"
			: "erpnext.manufacturing.page.eskd_bpak_matrix.eskd_bpak_matrix.assign";
		const args = combination
			? { combination }
			: {
					product: product_field.get_value(),
					board: $cell.attr("data-board"),
					ground_station: $cell.attr("data-gs"),
			  };
		frappe.call({ method, args, callback: () => render() });
	}

	frappe.call({
		method: "erpnext.manufacturing.page.eskd_bpak_matrix.eskd_bpak_matrix.get_products",
		callback: (r) => {
			const products = r.message || [];
			if (products.length && !product_field.get_value()) {
				product_field.set_value(products[0]);
			} else {
				render();
			}
		},
	});
};
