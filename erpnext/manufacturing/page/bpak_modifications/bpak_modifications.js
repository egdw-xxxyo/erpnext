frappe.pages["bpak-modifications"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Відомість модифікацій БпАК"),
		single_column: true,
	});

	const spec_field = page.add_field({
		label: __("Специфікація"),
		fieldtype: "Link",
		fieldname: "specification",
		options: "BpAK Specification",
		change: () => render(),
	});

	const $container = $('<div class="bpak-mods"></div>').appendTo(page.body);

	$("<style>")
		.text(
			`
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
		.bpak-mods td { vertical-align: middle; text-align: center; }
		.bpak-mods td.cell-name { text-align: left; }
		.bpak-mods a.icon-link {
			display: inline-block;
			color: var(--text-color);
			padding: 2px 4px;
		}
		.bpak-mods a.icon-link:hover { color: var(--primary); }
	`
		)
		.appendTo("head");

	function item_link(doctype, name, label) {
		const route = `/app/${doctype.toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(name)}`;
		const text = frappe.utils.escape_html(label || name);
		return `<a href="${route}" data-doctype="${doctype}" data-name="${frappe.utils.escape_html(
			name
		)}">${text}</a>`;
	}

	function item_icon_link(name, tooltip) {
		const route = `/app/item/${encodeURIComponent(name)}`;
		const tip = frappe.utils.escape_html(tooltip || name);
		return `<a href="${route}" class="icon-link" data-doctype="Item" data-name="${frappe.utils.escape_html(
			name
		)}" title="${tip}">
			<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
		</a>`;
	}

	function render() {
		const specification = spec_field.get_value();
		if (!specification) {
			$container.html(
				`<div class="text-muted" style="margin: 15px 0;">${__("Оберіть специфікацію")}</div>`
			);
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.page.bpak_modifications.bpak_modifications.get_data",
			args: { specification },
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
			html += `<td class="cell-name">${frappe.utils.escape_html(row.fpv_name || "")}</td>`;
			html += `<td>${item_link("Item", row.fpv_item, row.fpv_shifr)}</td>`;
			for (const g of gs) {
				const cell = row.cells[g.item];
				html += `<td>${cell ? item_icon_link(cell.item, cell.shifr) : ""}</td>`;
			}
			html += "</tr>";
		}
		html += "</tbody></table>";

		if (!rows.length) {
			html += `<div class="text-muted">${__("Немає модифікацій для цієї специфікації")}</div>`;
		}

		$container.html(html);
	}

	frappe.call({
		method: "erpnext.manufacturing.page.bpak_modifications.bpak_modifications.get_specifications",
		callback: (r) => {
			const specs = r.message || [];
			if (specs.length && !spec_field.get_value()) {
				spec_field.set_value(specs[0].name);
			} else {
				render();
			}
		},
	});
};
