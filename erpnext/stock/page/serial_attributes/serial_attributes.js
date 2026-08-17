frappe.pages["serial-attributes"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Serial Attributes"),
		single_column: true,
	});

	const METHOD = "erpnext.stock.page.serial_attributes.serial_attributes";

	let rows = [];
	let columns = [];
	const selected = new Set();

	const item_field = page.add_field({
		label: __("Item"),
		fieldtype: "Link",
		fieldname: "item_code",
		options: "Item",
		change: () => refresh(),
	});

	const item_group_field = page.add_field({
		label: __("Item Group"),
		fieldtype: "Link",
		fieldname: "item_group",
		options: "Item Group",
		change: () => refresh(),
	});

	const warehouse_field = page.add_field({
		label: __("Warehouse"),
		fieldtype: "Link",
		fieldname: "warehouse",
		options: "Warehouse",
		change: () => refresh(),
	});

	const status_field = page.add_field({
		label: __("Status"),
		fieldtype: "Select",
		fieldname: "status",
		options: ["", "Active", "Inactive", "Consumed", "Delivered", "Expired"],
		change: () => refresh(),
	});

	const attribute_field = page.add_field({
		label: __("Attribute"),
		fieldtype: "Link",
		fieldname: "attribute",
		options: "Additional Attribute",
		change: () => {
			value_field.set_value("");
			refresh();
		},
	});

	const value_field = page.add_field({
		label: __("Value"),
		fieldtype: "Link",
		fieldname: "value",
		options: "Additional Attribute Value",
		get_query: () => ({ filters: { attribute: attribute_field.get_value() || undefined } }),
		change: () => refresh(),
	});

	const missing_field = page.add_field({
		label: __("Only Missing This Attribute"),
		fieldtype: "Check",
		fieldname: "missing_only",
		change: () => refresh(),
	});

	page.set_primary_action(__("Set Attribute"), () => set_dialog([...selected]), "edit");
	page.add_menu_item(__("Set By Pasted Serial Numbers"), () => paste_dialog());
	page.add_menu_item(__("Reload"), () => refresh());

	const $body = $(`
		<div class="serial-attributes">
			<div class="sa-toolbar text-muted small"></div>
			<div class="sa-table"></div>
		</div>
	`).appendTo(page.body);

	$("<style>")
		.text(
			`
		.serial-attributes .sa-toolbar { margin: 6px 0 10px; }
		.serial-attributes table { font-size: 13px; width: 100%; }
		.serial-attributes th, .serial-attributes td { padding: 6px 8px; vertical-align: middle; }
		.serial-attributes td.sa-attr { cursor: pointer; }
		.serial-attributes td.sa-attr:hover { background: var(--fg-hover-color); }
		.serial-attributes td.sa-empty { color: var(--text-muted); font-style: italic; }
		.serial-attributes tr.sa-checked { background: var(--highlight-color); }
		.serial-attributes .sa-check { cursor: pointer; }
	`
		)
		.appendTo("head");

	function refresh() {
		frappe.call({
			method: `${METHOD}.get_serials`,
			args: {
				item_code: item_field.get_value(),
				item_group: item_group_field.get_value(),
				warehouse: warehouse_field.get_value(),
				status: status_field.get_value(),
				attribute: attribute_field.get_value(),
				value: value_field.get_value(),
				missing_only: missing_field.get_value() ? 1 : 0,
			},
			callback: (r) => {
				const data = r.message || {};
				rows = data.serials || [];
				columns = data.attributes || [];
				selected.clear();
				render();
			},
		});
	}

	function render() {
		if (!rows.length) {
			$body
				.find(".sa-table")
				.html(`<p class="text-muted">${__("No serial numbers match these filters")}</p>`);
			update_toolbar();
			return;
		}

		const head = columns.map((c) => `<th>${frappe.utils.escape_html(c)}</th>`).join("");

		const body = rows
			.map((row) => {
				const cells = columns
					.map((attribute) => {
						const attr = (row.attributes || {})[attribute];
						const label = attr
							? frappe.utils.escape_html(attr.label || attr.value)
							: __("Not set");
						const title = attr && attr.notes ? frappe.utils.escape_html(attr.notes) : "";
						return `<td class="sa-attr ${attr ? "" : "sa-empty"}"
								data-serial="${frappe.utils.escape_html(row.name)}"
								data-attribute="${frappe.utils.escape_html(attribute)}"
								title="${title}">${label}</td>`;
					})
					.join("");

				return `
					<tr data-serial="${frappe.utils.escape_html(row.name)}">
						<td><input type="checkbox" class="sa-check" data-serial="${frappe.utils.escape_html(row.name)}"></td>
						<td><a href="/app/serial-no/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(row.name)}</a></td>
						<td>${frappe.utils.escape_html(row.item_code || "")}</td>
						<td>${frappe.utils.escape_html(row.warehouse || "")}</td>
						<td>${frappe.utils.escape_html(row.status || "")}</td>
						${cells}
					</tr>`;
			})
			.join("");

		$body.find(".sa-table").html(`
			<table class="table table-bordered">
				<thead>
					<tr>
						<th style="width: 30px"><input type="checkbox" class="sa-check-all"></th>
						<th>${__("Serial No")}</th>
						<th>${__("Item")}</th>
						<th>${__("Warehouse")}</th>
						<th>${__("Status")}</th>
						${head}
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		`);

		$body.find(".sa-check-all").on("change", function () {
			const checked = this.checked;
			$body.find(".sa-check").prop("checked", checked);
			selected.clear();
			if (checked) rows.forEach((row) => selected.add(row.name));
			$body.find("tbody tr").toggleClass("sa-checked", checked);
			update_toolbar();
		});

		$body.find(".sa-check").on("change", function () {
			const serial = $(this).data("serial");
			if (this.checked) selected.add(serial);
			else selected.delete(serial);
			$(this).closest("tr").toggleClass("sa-checked", this.checked);
			update_toolbar();
		});

		$body.find("td.sa-attr").on("click", function () {
			set_dialog([$(this).data("serial")], $(this).data("attribute"));
		});

		update_toolbar();
	}

	function update_toolbar() {
		$body
			.find(".sa-toolbar")
			.html(`${__("Shown: {0}", [rows.length])} &nbsp;·&nbsp; ${__("Selected: {0}", [selected.size])}`);
	}

	function set_dialog(serials, attribute) {
		if (!serials || !serials.length) {
			frappe.msgprint(__("Select at least one serial number"));
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Set Attribute for {0} Serial No(s)", [serials.length]),
			fields: [
				{
					label: __("Attribute"),
					fieldname: "attribute",
					fieldtype: "Link",
					options: "Additional Attribute",
					reqd: 1,
					default: attribute || attribute_field.get_value(),
					onchange: () => dialog.set_value("value", ""),
				},
				{
					label: __("Value"),
					fieldname: "value",
					fieldtype: "Link",
					options: "Additional Attribute Value",
					depends_on: "eval:!doc.clear",
					get_query: () => ({ filters: { attribute: dialog.get_value("attribute") || undefined } }),
				},
				{ fieldtype: "Column Break" },
				{
					label: __("Overwrite Existing Value"),
					fieldname: "overwrite",
					fieldtype: "Check",
					default: 1,
					description: __("Uncheck to fill only serials that have no value yet"),
				},
				{
					label: __("Clear Attribute"),
					fieldname: "clear",
					fieldtype: "Check",
					description: __("Remove this attribute from the selected serial numbers"),
				},
				{ fieldtype: "Section Break" },
				{ label: __("Notes"), fieldname: "notes", fieldtype: "Small Text" },
			],
			primary_action_label: __("Apply"),
			primary_action: (values) => {
				frappe.call({
					method: `${METHOD}.set_attribute`,
					args: {
						serials: serials,
						attribute: values.attribute,
						value: values.value,
						notes: values.notes,
						overwrite: values.overwrite ? 1 : 0,
						clear: values.clear ? 1 : 0,
					},
					freeze: true,
					freeze_message: __("Updating serial numbers..."),
					callback: (r) => {
						dialog.hide();
						show_result(r.message || {});
						refresh();
					},
				});
			},
		});

		dialog.show();
	}

	function show_result(result) {
		const parts = [__("Updated: {0}", [(result.updated || []).length])];
		if ((result.skipped || []).length) {
			parts.push(__("Skipped (already set): {0}", [result.skipped.length]));
		}
		if ((result.failed || []).length) {
			parts.push(__("Failed: {0}", [result.failed.length]));
			parts.push(
				result.failed
					.slice(0, 10)
					.map((f) => `${frappe.utils.escape_html(f.serial)}: ${frappe.utils.escape_html(f.error)}`)
					.join("<br>")
			);
		}
		frappe.msgprint({ title: __("Bulk Update"), message: parts.join("<br>"), indicator: "blue" });
	}

	function paste_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Set By Pasted Serial Numbers"),
			fields: [
				{
					label: __("Serial Numbers"),
					fieldname: "serials",
					fieldtype: "Small Text",
					reqd: 1,
					description: __("Separate by new line, comma, semicolon, tab or space"),
				},
			],
			primary_action_label: __("Check List"),
			primary_action: (values) => {
				frappe.call({
					method: `${METHOD}.parse_serials`,
					args: { text: values.serials, item_code: item_field.get_value() },
					callback: (r) => {
						const parsed = r.message || {};
						const found = parsed.found || [];
						const unknown = parsed.unknown || [];
						const wrong_item = parsed.wrong_item || [];

						if (unknown.length || wrong_item.length) {
							const lines = [];
							if (unknown.length) {
								lines.push(
									`<b>${__("Unknown serial numbers: {0}", [unknown.length])}</b><br>` +
										frappe.utils.escape_html(unknown.slice(0, 20).join(", "))
								);
							}
							if (wrong_item.length) {
								lines.push(
									`<b>${__("Belong to another Item: {0}", [wrong_item.length])}</b><br>` +
										frappe.utils.escape_html(wrong_item.slice(0, 20).join(", "))
								);
							}
							frappe.msgprint({
								title: __("Some Serial Numbers Were Skipped"),
								message: lines.join("<br><br>"),
								indicator: "orange",
							});
						}

						if (!found.length) {
							return;
						}

						dialog.hide();
						set_dialog(found);
					},
				});
			},
		});

		dialog.show();
	}

	refresh();
};
