const BPAK_MATRIX_METHOD = "erpnext.manufacturing.page.eskd_bpak_matrix.eskd_bpak_matrix";

frappe.pages["eskd-bpak-matrix"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("BpAK Modification List"),
		single_column: true,
	});

	const list_field = page.add_field({
		label: __("Modification List"),
		fieldtype: "Select",
		fieldname: "modification_list",
		change: () => render(),
	});
	list_field.$wrapper.css({ "min-width": "480px" });

	const $container = $('<div class="bpak-matrix"></div>').appendTo(page.body);
	let items = {};

	$("<style>")
		.text(
			`
		.bpak-matrix .matrix-title { text-align: center; margin: 12px 0; font-size: 15px; }
		.bpak-matrix table { font-size: 13px; width: auto; }
		.bpak-matrix th.gs-col {
			writing-mode: vertical-rl;
			transform: rotate(180deg);
			vertical-align: bottom;
			text-align: left;
			white-space: nowrap;
			padding: 8px 4px;
			height: 190px;
			width: 40px;
			min-width: 40px;
		}
		.bpak-matrix th.gs-col a { color: inherit; text-decoration: none; }
		.bpak-matrix td { vertical-align: middle; white-space: nowrap; }
		.bpak-matrix td.gs-cell { text-align: center; width: 40px; min-width: 40px; }
		.bpak-matrix td.gs-marked { background: var(--gray-500); cursor: pointer; }
		.bpak-matrix td.gs-marked:hover { background: var(--gray-600); }
		.bpak-matrix .items-btn {
			cursor: pointer;
			color: var(--blue-600);
			white-space: nowrap;
			margin-left: 4px;
		}
		.bpak-matrix td.gs-marked .items-btn { color: var(--white); margin-left: 0; }
		.bpak-matrix th.gs-col .items-btn { transform: rotate(180deg); display: inline-block; }
	`
		)
		.appendTo("head");

	const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

	function spec_link(name, label) {
		if (!name) return "";
		return `<a href="/app/specification/${encodeURIComponent(name)}">${esc(label || name)}</a>`;
	}

	function items_button(specification) {
		const found = items[specification];
		if (!found || !found.length) return "";
		return `<span class="items-btn" data-spec="${esc(specification)}" title="${esc(
			__("Items: {0}", [found.length])
		)}"><i class="fa fa-cube"></i> ${found.length}</span>`;
	}

	function show_items(specification) {
		const found = items[specification] || [];
		const rows = found
			.map(
				(item) =>
					`<tr><td><a href="/app/item/${encodeURIComponent(item.name)}">${esc(
						item.name
					)}</a></td>` + `<td>${esc(item.item_name)}</td><td>${esc(item.variant_of)}</td></tr>`
			)
			.join("");
		const dialog = new frappe.ui.Dialog({
			title: __("Items of {0}", [specification]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "items",
					options: `<table class="table table-bordered"><thead><tr><th>${__(
						"Item Code"
					)}</th><th>${__("Item Name")}</th><th>${__(
						"Variant Of"
					)}</th></tr></thead><tbody>${rows}</tbody></table>`,
				},
			],
		});
		dialog.show();
	}

	function load_lists() {
		frappe.call({
			method: `${BPAK_MATRIX_METHOD}.get_modification_lists`,
			callback: (r) => {
				const lists = r.message || [];
				list_field.df.options = lists.map((l) => ({
					value: l.name,
					label: `${l.specification_name} ${l.display_code}`,
				}));
				list_field.refresh();
				if (lists.length) {
					list_field.set_value(lists[0].name);
				} else {
					$container.html(`<div class="text-muted">${__("No modification lists yet")}</div>`);
				}
			},
		});
	}

	function render() {
		const modification_list = list_field.get_value();
		if (!modification_list) return;
		frappe.call({
			method: `${BPAK_MATRIX_METHOD}.get_matrix`,
			args: { modification_list },
			callback: (r) => paint(r.message),
		});
	}

	function paint(data) {
		if (!data) return;
		items = data.items || {};
		const columns = data.columns || [];
		const rows = data.rows || [];
		const selected = (list_field.df.options || []).find((o) => o.value === list_field.get_value());

		let html = `<div class="matrix-title">${esc(selected ? selected.label : "")} ${items_button(
			list_field.get_value()
		)}</div>`;
		html += '<div style="overflow-x: auto"><table class="table table-bordered">';
		html += "<thead><tr>";
		html += `<th>${__("Modification")}</th>`;
		html += `<th>${__("Name")}</th>`;
		html += `<th>${__("Board Specification")}</th>`;
		for (const column of columns) {
			html += `<th class="gs-col">${spec_link(column.name, column.code)} ${items_button(
				column.name
			)}</th>`;
		}
		html += "</tr></thead><tbody>";

		for (const row of rows) {
			html += "<tr>";
			html += `<td>${spec_link(row.modification, __("Modification {0}", [row.ordinal]))}</td>`;
			html += `<td>${esc(row.description)}</td>`;
			html += `<td>${spec_link(row.board, row.board_code)} ${items_button(row.board)}</td>`;
			for (const column of columns) {
				if (row.ground_station === column.name) {
					html += `<td class="gs-cell gs-marked" data-spec="${esc(row.modification)}" title="${esc(
						row.code
					)}">${items_button(row.modification)}</td>`;
				} else {
					html += '<td class="gs-cell"></td>';
				}
			}
			html += "</tr>";
		}
		html += "</tbody></table></div>";

		if (!rows.length) {
			html += `<div class="text-muted">${__("No modifications in this list yet")}</div>`;
		}

		$container.html(html);
		$container.find(".items-btn").on("click", function (e) {
			e.preventDefault();
			e.stopPropagation();
			show_items($(this).attr("data-spec"));
		});
		$container.find("td.gs-marked").on("click", function () {
			frappe.set_route("Form", "Specification", $(this).attr("data-spec"));
		});
	}

	load_lists();
};
