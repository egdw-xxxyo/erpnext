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
		html += '<table class="table table-bordered" style="font-size: 13px;">';
		html += "<thead><tr>";
		html += `<th>${__("Модифікація")}</th>`;
		html += `<th>${__("Найменування")}</th>`;
		html += `<th>${__("Шифр FPV")}</th>`;
		for (const g of gs) html += `<th>${frappe.utils.escape_html(g)}</th>`;
		html += "</tr></thead><tbody>";

		for (const row of rows) {
			html += "<tr>";
			html += `<td>${__("Модифікація")} ${row.mod_num}</td>`;
			html += `<td>${frappe.utils.escape_html(row.name || "")}</td>`;
			html += `<td>${frappe.utils.escape_html(row.fpv_shifr || "")}</td>`;
			for (const g of gs) {
				const v = row.cells[g];
				html += `<td>${v ? frappe.utils.escape_html(v) : ""}</td>`;
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
