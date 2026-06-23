frappe.pages["bpak-modifications"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Відомість модифікацій БпАК"),
		single_column: true,
	});

	const size_field = page.add_field({
		label: __("Розмір"),
		fieldtype: "Select",
		fieldname: "size",
		options: ["15", "10"],
		default: "15",
		change: () => render(),
	});

	const $container = $('<div class="bpak-mods"></div>').appendTo(page.body);

	$('<style>').text(`
		.bpak-mods table { font-size: 13px; }
		.bpak-mods th.gs-col {
			writing-mode: vertical-rl;
			transform: rotate(180deg);
			vertical-align: bottom;
			text-align: left;
			white-space: nowrap;
			padding: 8px 4px;
			height: 180px;
			min-width: 36px;
			max-width: 36px;
		}
		.bpak-mods th.gs-col a { color: inherit; text-decoration: none; }
		.bpak-mods td { vertical-align: middle; }
	`).appendTo('head');

	function item_link(doctype, name, label) {
		const route = `/app/${doctype.toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(name)}`;
		const text = frappe.utils.escape_html(label || name);
		return `<a href="${route}" data-doctype="${doctype}" data-name="${frappe.utils.escape_html(name)}">${text}</a>`;
	}

	function render() {
		const size = size_field.get_value() || "15";
		frappe.call({
			method: "erpnext.manufacturing.page.bpak_modifications.bpak_modifications.get_data",
			args: { size: size, line: "FO" },
			callback: (r) => paint(r.message),
		});
	}

	function paint(data) {
		if (!data) return;
		const gs = data.gs_columns || [];
		const rows = data.rows || [];

		let html = `<h3 style="margin: 15px 0;">${frappe.utils.escape_html(data.title)}</h3>`;
		html += '<table class="table table-bordered">';
		html += "<thead><tr>";
		html += `<th>${__("Модифікація")}</th>`;
		html += `<th>${__("Найменування")}</th>`;
		html += `<th>${__("Шифр FPV")}</th>`;
		for (const g of gs) {
			html += `<th class="gs-col">${item_link("Item", g.item, g.shifr)}</th>`;
		}
		html += "</tr></thead><tbody>";

		for (const row of rows) {
			html += "<tr>";
			html += `<td>${__("Модифікація")} ${row.mod_num}</td>`;
			html += `<td>${frappe.utils.escape_html(row.name || "")}</td>`;
			html += `<td>${item_link("Item", row.fpv_item, row.fpv_shifr)}</td>`;
			for (const g of gs) {
				const cell = row.cells[g.shifr];
				html += `<td>${cell ? item_link("Item", cell.item, cell.shifr) : ""}</td>`;
			}
			html += "</tr>";
		}
		html += "</tbody></table>";

		if (!rows.length) {
			html += `<div class="text-muted">${__("Немає FPV комбо для цього розміру")}</div>`;
		}

		$container.html(html);
	}

	render();
};
