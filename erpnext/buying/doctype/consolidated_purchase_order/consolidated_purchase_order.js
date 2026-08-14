frappe.ui.form.on("Consolidated Purchase Order", {
	setup(frm) {
		frappe.meta.get_docfield(
			"Consolidated Purchase Supplier Invoice",
			"invoice_document",
			frm.doc.name
		).formatter = (value, df, options, doc) => {
			const file_name = value || get_file_name(doc.invoice_pdf);
			if (!file_name || !doc.invoice_pdf) return "";
			return `<a href="${frappe.utils.escape_html(doc.invoice_pdf)}" target="_blank">${frappe.utils.escape_html(
				file_name
			)}</a>`;
		};
		frm.set_query("supplier", "supplier_invoices", () => ({
			filters: {
				name: ["in", get_order_suppliers(frm)],
			},
		}));
	},

	refresh(frm) {
		frm.fields_dict.supplier_invoices.grid.update_docfield_property("invoice_pdf", "options", {
			restrictions: { allowed_file_types: [".pdf"] },
			allow_web_link: false,
		});
		frm.fields_dict.supplier_invoices.grid.update_docfield_property("supplier", "hidden", 0);
		frm.fields_dict.supplier_invoices.grid.update_docfield_property("supplier", "reqd", 1);
		set_table_row_number_labels(frm);
		setTimeout(() => set_table_row_number_labels(frm), 100);
		frm.trigger("render_purchase_orders");
		if (frm.doc.docstatus !== 1) return;

		frm.add_custom_button(
			__("Purchase Invoice"),
			() => {
				frappe
					.call({
						method: "erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_purchase_invoice_options",
						args: { source_name: frm.doc.name },
					})
					.then((response) => {
						const orders = response.message || [];
						if (!orders.length) {
							frappe.msgprint(__("There are no suppliers with unbilled Purchase Orders."));
							return;
						}

						const suppliers = [...new Map(orders.map((row) => [row.supplier, row])).values()];
						const dialog = new frappe.ui.Dialog({
							title: __("Select Supplier for Purchase Invoice"),
							fields: [
								{
									fieldname: "supplier",
									fieldtype: "Select",
									label: __("Supplier"),
									options: suppliers.map((row) => row.supplier),
									reqd: 1,
									description: suppliers
										.map(
											(row) =>
												`${frappe.utils.escape_html(
													row.supplier_name || row.supplier
												)} — ${format_currency(row.grand_total, row.currency)} — ${__(
													"Billed"
												)}: ${flt(row.per_billed)}%`
										)
										.join("<br>"),
								},
							],
							primary_action_label: __("Create"),
							primary_action(values) {
								dialog.hide();
								frappe.model.open_mapped_doc({
									method: "erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.make_purchase_invoice",
									frm,
									args: { supplier: values.supplier },
								});
							},
						});
						dialog.show();
					});
			},
			__("Create")
		);
	},

	company(frm) {
		if (!frm.doc.company) return;
		frappe.db.get_value("Company", frm.doc.company, "default_currency").then((response) => {
			frm.set_value("currency", response.message.default_currency);
		});
	},

	set_supplier(frm) {
		if (!frm.doc.set_supplier) return;
		(frm.doc.items || []).forEach((row) => {
			frappe.model.set_value(row.doctype, row.name, "supplier", frm.doc.set_supplier);
		});
	},

	render_purchase_orders(frm) {
		const field = frm.get_field("purchase_orders_html");
		if (!field || frm.is_new()) return;
		frappe
			.call({
				method: "erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_purchase_invoice_options",
				args: { source_name: frm.doc.name },
			})
			.then((response) => {
				const rows = response.message || [];
				if (!rows.length) {
					field.$wrapper.html(
						`<div class="text-muted">${__("Purchase Orders have not been created yet.")}</div>`
					);
					return;
				}
				const body = rows
					.map(
						(row) => `<tr>
						<td><a href="/app/purchase-order/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
							row.name
						)}</a></td>
						<td>${frappe.utils.escape_html(row.supplier_name || row.supplier)}</td>
						<td class="text-right">${format_currency(row.grand_total, row.currency)}</td>
						<td class="text-right">${flt(row.per_billed)}%</td>
					</tr>`
					)
					.join("");
				field.$wrapper
					.html(`<div class="table-responsive"><table class="table table-bordered table-sm">
				<thead><tr><th>${__("Purchase Order")}</th><th>${__("Supplier")}</th><th class="text-right">${__(
					"Grand Total"
				)}</th><th class="text-right">${__(
					"Billed"
				)}</th></tr></thead><tbody>${body}</tbody></table></div>`);
			});
	},
});

frappe.ui.form.on("Consolidated Purchase Order Item", {
	items_add(frm, cdt, cdn) {
		if (frm.doc.set_supplier) {
			frappe.model.set_value(cdt, cdn, "supplier", frm.doc.set_supplier);
		}
	},
	qty(frm, cdt, cdn) {
		calculate_consolidated_item(frm, cdt, cdn);
	},
	rate(frm, cdt, cdn) {
		calculate_consolidated_item(frm, cdt, cdn);
	},
});

frappe.ui.form.on("Consolidated Purchase Supplier Invoice", {
	invoice_pdf(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "invoice_document", get_file_name(row.invoice_pdf));
		if (!row.invoice_pdf || row.invoice_pdf.split("?")[0].toLowerCase().endsWith(".pdf")) {
			return;
		}

		frappe.model.set_value(cdt, cdn, "invoice_pdf", null);
		frappe.msgprint({
			title: __("Unsupported File Format"),
			message: __("The supplier invoice must be a PDF file."),
			indicator: "red",
		});
	},
});

function get_order_suppliers(frm) {
	const suppliers = (frm.doc.items || []).map((row) => row.supplier).filter(Boolean);
	return [...new Set(suppliers)].length ? [...new Set(suppliers)] : [""];
}

function set_table_row_number_labels(frm) {
	["items", "supplier_invoices"].forEach((fieldname) => {
		frm.fields_dict[fieldname].grid.wrapper.find(".grid-heading-row .row-index span").text("\u2116");
	});
}

function get_file_name(file_url) {
	if (!file_url) return null;
	const path = file_url.split("?")[0];
	return decodeURIComponent(path.substring(path.lastIndexOf("/") + 1));
}

function calculate_consolidated_item(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
	frm.set_value(
		"total_qty",
		(frm.doc.items || []).reduce((total, item) => total + flt(item.qty), 0)
	);
	frm.set_value(
		"grand_total",
		(frm.doc.items || []).reduce((total, item) => total + flt(item.amount), 0)
	);
}
