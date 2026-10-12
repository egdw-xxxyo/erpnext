frappe.ui.form.on("Consolidated Purchase Order", { refresh: render_supplier_invoice_actions });
frappe.ui.form.on("Consolidated Purchase Supplier Invoice", {
	supplier: render_supplier_invoice_actions,
	invoice_pdf: render_supplier_invoice_actions,
	supplier_invoices_remove: render_supplier_invoice_actions,
});
function render_supplier_invoice_actions(frm) {
	const field = frm.get_field("supplier_invoices");
	field?.$wrapper.find(".supplier-invoice-actions").remove();
	if (!field || frm.doc.docstatus === 2) return;
	if (
		frappe.session.user !== "Administrator" &&
		!(
			frappe.user.has_role("Закупівельник") &&
			(frm.is_new() || [frm.doc.owner, frm.doc.initiator_user].includes(frappe.session.user))
		)
	)
		return;
	const editable =
		frm.doc.docstatus === 0 &&
		!["Перевірка підрозділу", "Фінальне погодження", "Погоджено"].includes(frm.doc.workflow_state) &&
		(frm.is_new() ? frm.perm?.[0]?.create : frm.perm?.[0]?.write);
	if (editable) frm.set_query("supplier", "supplier_invoices", () => ({}));
	const actions = $(
		'<div class="supplier-invoice-actions mt-3 d-flex flex-wrap" style="gap:8px"></div>'
	).appendTo(field.$wrapper);
	const add_action = (label, mode) => {
		$('<button type="button" class="btn btn-default btn-sm"></button>')
			.text(__(label))
			.appendTo(actions)
			.on("click", () => {
				if (mode === "match" && frm.is_dirty()) {
					frappe.msgprint(__("Save the order and supplier invoices before matching items."));
					return;
				}
				if (!(frm.doc.supplier_invoices || []).some((row) => row.supplier && row.invoice_pdf)) {
					frappe.msgprint(__("Select a supplier invoice from this draft."));
					return;
				}
				select_supplier_invoice(frm, mode);
			});
	};
	if (!frm.is_new()) add_action("Match supplier item names", "match");
	if (editable) add_action("Prefill from PDF", "prefill");
}

function select_supplier_invoice(frm, mode = "match") {
	const invoices = frm.doc.supplier_invoices.filter((row) => row.supplier && row.invoice_pdf);
	const dialog = new frappe.ui.Dialog({
		title: __("Select supplier invoice"),
		fields: [
			{
				fieldname: "invoice",
				default: invoices[0].name,
				fieldtype: "Select",
				label: __("Supplier Invoice PDF"),
				reqd: 1,
				options: invoices.map((row) => ({
					value: row.name,
					label: `${row.supplier} — ${row.invoice_document || row.invoice_pdf.split("/").pop()}`,
				})),
			},
		],
		primary_action_label: __("Read invoice items"),
		async primary_action(values) {
			const invoice = invoices.find((row) => row.name === values.invoice);
			const snapshot = JSON.stringify(frm.doc);
			const response = await frappe.call({
				method: `erpnext.buying.procurement_supplier_item_matching.${
					mode === "prefill" ? "get_prefill_preview" : "get_matching_preview"
				}`,
				args: {
					...(mode === "prefill" ? { draft_doc: snapshot } : { source_name: frm.doc.name }),
					supplier: invoice.supplier,
					file_url: invoice.invoice_pdf,
				},
				freeze: true,
				freeze_message: __("Reading invoice items..."),
			});
			dialog.hide();
			if (mode === "prefill") show_supplier_item_prefill(frm, invoice, response.message, snapshot);
			else show_supplier_item_matches(frm, invoice, response.message);
		},
	});
	dialog.show();
}

function show_supplier_item_matches(frm, invoice, result) {
	const escape = frappe.utils.escape_html;
	const number = (value) => (value == null ? "—" : escape(String(value)));
	const dialog = new frappe.ui.Dialog({
		title: __("Confirm supplier item names"),
		size: "extra-large",
		fields: [{ fieldname: "matches", fieldtype: "HTML" }],
		primary_action_label: __("Save confirmed matches"),
		async primary_action() {
			const mappings = [];
			for (const row of dialog.fields_dict.matches.$wrapper.find("tr[data-invoice-row]").toArray()) {
				if (!$(row).find("input[type=checkbox]").is(":checked")) continue;
				const target = $(row).find("select").val();
				if (!target) {
					frappe.msgprint(__("Choose an order item for every checked invoice row."));
					return;
				}
				mappings.push({ invoice_row: row.dataset.invoiceRow, order_row: target });
			}
			if (!mappings.length) {
				frappe.msgprint(__("Select invoice rows and their matching order items."));
				return;
			}
			const response = await frappe.call({
				method: "erpnext.buying.procurement_supplier_item_matching.confirm_matches",
				args: {
					source_name: frm.doc.name,
					supplier: invoice.supplier,
					file_url: invoice.invoice_pdf,
					mappings,
				},
				freeze: true,
			});
			dialog.hide();
			frappe.msgprint(
				__("Saved {0} new matches; {1} were already saved.", [
					response.message.saved,
					response.message.already_saved,
				])
			);
		},
	});
	const pdf = `<a href="${escape(invoice.invoice_pdf)}" target="_blank" rel="noopener noreferrer">${__(
		"Open PDF"
	)}</a>`;
	let html = `<p>${pdf}</p><p class="text-muted">${__(
		"Check the PDF and tick only confirmed matches. Order quantities and prices will not change."
	)}</p>`;
	if (!result.rows.length) {
		html += `<div class="alert alert-warning">${__(
			"Could not read the invoice item table. A text PDF with name and quantity columns is required. No matches were saved."
		)}</div>`;
		dialog.get_primary_btn().hide();
	} else {
		html += `<div class="alert alert-warning">${__(
			"PDF extraction may miss or merge rows. Verify names, units and VAT basis against the PDF; quantity and price are only hints."
		)}</div>`;
		html += `<div style="overflow:auto"><table class="table table-bordered"><thead><tr>${[
			"Confirm",
			"Supplier Item Name",
			"Supplier article",
			"Quantity",
			"Rate",
			"Order item",
			"Matching hints",
		]
			.map((label) =>
				label === "Confirm"
					? `<th><label><input type="checkbox" data-select-all> ${__("Select all")}</label></th>`
					: `<th>${__(label)}</th>`
			)
			.join("")}</tr></thead><tbody>`;
		for (const row of result.rows) {
			const options = [`<option value="">${__("Select an order item")}</option>`];
			for (const target of result.order_rows) {
				options.push(
					`<option value="${escape(target.name)}" ${
						target.name === row.suggested_order_row ? "selected" : ""
					}>${escape(
						`#${target.idx} ${target.item_code} — ${target.item_name} | ${target.qty} ${target.uom} | ${target.rate}`
					)}</option>`
				);
			}
			const hint =
				row.candidates.find((candidate) => candidate.order_row === row.suggested_order_row) ||
				row.candidates[0];
			html += `<tr data-invoice-row="${escape(row.id)}"><td><input type="checkbox" aria-label="${escape(
				__("Confirm")
			)}"></td><td>${escape(row.supplier_item_name)}<div class="text-muted">${__("Page {0}", [
				row.page,
			])}</div></td><td>${escape(row.supplier_part_no)}</td><td>${number(row.qty)} ${escape(
				row.uom
			)}</td><td>${number(
				row.rate
			)}</td><td><select class="form-control" style="min-width:280px" aria-label="${escape(
				__("Order item")
			)}">${options.join("")}</select></td><td>${(hint?.reasons || [])
				.map((reason) => escape(__(reason)))
				.join(", ")}</td></tr>`;
		}
		html += "</tbody></table></div>";
	}
	dialog.fields_dict.matches.$wrapper.html(html);
	const wrapper = dialog.fields_dict.matches.$wrapper;
	wrapper.on("change", "input[data-select-all]", function () {
		wrapper
			.find("tr[data-invoice-row] input[type=checkbox]")
			.prop("checked", this.checked)
			.trigger("change");
	});
	wrapper.on("change", "tr[data-invoice-row] input[type=checkbox]", () => {
		const checks = wrapper.find("tr[data-invoice-row] input[type=checkbox]").toArray();
		const count = checks.filter((input) => input.checked).length;
		wrapper
			.find("input[data-select-all]")
			.prop("checked", count === checks.length)
			.prop("indeterminate", count > 0 && count < checks.length);
	});
	dialog.show();
}

function show_supplier_item_prefill(frm, invoice, result, snapshot) {
	const escape = frappe.utils.escape_html;
	const dialog = new frappe.ui.Dialog({
		title: __("Prefill from PDF"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p><a href="${escape(
					invoice.invoice_pdf
				)}" target="_blank" rel="noopener noreferrer">${__(
					"Open PDF"
				)}</a></p><p class="text-muted">${__(
					"Saved supplier names and articles preselect our Items. Check the matches; choose unknown or ambiguous Items manually. Existing order rows will remain."
				)}</p>`,
			},
			{
				fieldname: "import_values",
				fieldtype: "Check",
				label: __("Prefill quantity and price from PDF"),
				default: 0,
				description: __(
					"Verify quantities, units, prices and VAT against the PDF before saving the order."
				),
			},
			{
				fieldname: "rows",
				fieldtype: "Table",
				label: __("Invoice items"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				data: result.rows.map((row) => ({
					...row,
					invoice_row: row.id,
					__checked: row.suggested_item_code ? 1 : 0,
					item_code: row.suggested_item_code || "",
				})),
				fields: [
					{ fieldname: "invoice_row", fieldtype: "Data", hidden: 1 },
					{
						fieldname: "supplier_item_name",
						fieldtype: "Data",
						label: __("Supplier Item Name"),
						read_only: 1,
						in_list_view: 1,
						columns: 3,
					},
					{
						fieldname: "supplier_part_no",
						fieldtype: "Data",
						label: __("Supplier article"),
						read_only: 1,
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldname: "qty",
						fieldtype: "Float",
						label: __("PDF quantity"),
						read_only: 1,
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldname: "rate",
						fieldtype: "Float",
						label: __("PDF price"),
						read_only: 1,
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldname: "item_code",
						fieldtype: "Link",
						options: "Item",
						label: __("Item Code"),
						in_list_view: 1,
						columns: 3,
						get_query: () => ({ filters: { disabled: 0, has_variants: 0, is_purchase_item: 1 } }),
					},
				],
			},
		],
		primary_action_label: __("Add selected items"),
		async primary_action(values) {
			const selected = dialog.fields_dict.rows.grid.get_selected_children();
			if (!selected.length || selected.some((row) => !row.item_code)) {
				frappe.msgprint(__("Tick invoice rows and select our Item for each one."));
				return;
			}
			if (JSON.stringify(frm.doc) !== snapshot) {
				frappe.msgprint(__("The order changed. Open the PDF prefill again."));
				return;
			}
			const response = await frappe.call({
				method: "erpnext.buying.procurement_supplier_item_matching.prepare_prefill_items",
				args: {
					draft_doc: snapshot,
					import_values: values.import_values || 0,
					supplier: invoice.supplier,
					file_url: invoice.invoice_pdf,
					mappings: selected.map((row) => ({
						invoice_row: row.invoice_row,
						item_code: row.item_code,
					})),
				},
				freeze: true,
			});
			if (JSON.stringify(frm.doc) !== snapshot) {
				frappe.msgprint(__("The order changed. Open the PDF prefill again."));
				return;
			}
			for (const row of response.message.items) {
				const added = frm.add_child("items", row);
				await frm.script_manager.trigger("qty", added.doctype, added.name);
			}
			frm.refresh_field("items");
			frm.trigger("render_supplier_contacts");
			frm.dirty();
			dialog.hide();
			frappe.msgprint(
				__(
					"Items were added to the draft. Verify quantities, units, prices and VAT against the PDF before saving."
				)
			);
			if (response.message.missing_values)
				frappe.msgprint(
					__("Some PDF quantities or prices could not be read. Fill the missing values manually.")
				);
		},
	});
	if (!result.rows.length) {
		dialog.get_primary_btn().hide();
		dialog.fields_dict.rows.$wrapper.hide();
		dialog.$body.append(
			$('<div class="alert alert-warning"></div>').text(
				__(
					"Could not read the invoice item table. A text PDF with name and quantity columns is required. No matches were saved."
				)
			)
		);
	}
	dialog.show();
}
