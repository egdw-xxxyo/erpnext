const supplierVatDisplayMethod = "erpnext.accounts.supplier_vat_display.get_supplier_vat_display";

async function render_supplier_vat_display(frm) {
	const field = frm.get_field("custom_supplier_vat_totals");
	if (!field) return;
	const request = (frm.__vat_display_request || 0) + 1;
	frm.__vat_display_request = request;
	const response = await frappe.call({ method: supplierVatDisplayMethod, args: { doc: frm.doc } });
	if (request !== frm.__vat_display_request) return;
	const data = response.message;
	frm.doc.custom_supplier_is_vat_payer = data.payer ? 1 : 0;
	frm.refresh_field("custom_supplier_is_vat_payer");
	const table =
		frm.doctype === "Purchase Invoice"
			? "items"
			: frm.doctype === "Payment Request"
			? "payment_reference"
			: "references";
	const grid = frm.fields_dict[table]?.grid;
	const item = frm.doctype === "Purchase Invoice";
	const fields = item
		? ["custom_vat_net_rate", "custom_vat_gross_rate", "custom_vat_gross_amount"]
		: ["custom_vat_net_amount", "custom_vat_amount"];
	const visible = Boolean(data.visible);
	if (grid) {
		for (const name of fields) {
			grid.update_docfield_property(name, "hidden", visible ? 0 : 1);
			grid.update_docfield_property(name, "in_list_view", visible ? 1 : 0);
			grid.update_docfield_property(name, "is_virtual", 0);
			grid.update_docfield_property(
				name,
				"options",
				frm.doctype === "Payment Entry" ? "parent.paid_to_account_currency" : "parent.currency"
			);
		}
		if (item) {
			grid.update_docfield_property(
				"custom_vat_net_rate",
				"hidden",
				visible && (data.payer || data.totals.vat !== 0) ? 0 : 1
			);
			// Keep the accounting input accessible; VAT fields are display-only projections.
			// Do not override read_only: receipt-linked rows retain standard rate restrictions.
			grid.update_docfield_property("rate", "in_list_view", 1);
			grid.update_docfield_property("rate", "label", __("Input price"));
			grid.update_docfield_property(
				"custom_vat_gross_rate",
				"label",
				__("Price including VAT (calculated)")
			);
			grid.update_docfield_property("amount", "in_list_view", visible ? 0 : 1);
		}
		const widths =
			frm.doctype === "Payment Entry"
				? {
						reference_doctype: 1,
						reference_name: 3,
						due_date: 1,
						total_amount: 1,
						outstanding_amount: 1,
						allocated_amount: 1,
				  }
				: frm.doctype === "Payment Request"
				? { payment_term: 2, description: 3, due_date: 2, amount: 1 }
				: { item_code: 2, qty: 1, rate: 1 };
		for (const [name, columns] of Object.entries(widths))
			grid.update_docfield_property(name, "columns", columns);
		if (frm.__vat_display_visible !== visible) {
			grid.reset_grid();
			frm.__vat_display_visible = visible;
		}
		for (const row of frm.doc[table] || []) {
			const values = data.rows?.[row.name] || {};
			row.custom_vat_net_rate = values.net_rate;
			row.custom_vat_gross_rate = values.gross_rate;
			row.custom_vat_gross_amount = values.gross_amount;
			row.custom_vat_net_amount = values.net;
			row.custom_vat_amount = values.vat;
		}
		frm.refresh_field(table);
	}
	if (!visible) {
		field.$wrapper.empty();
		return;
	}
	const escape = frappe.utils.escape_html;
	const money = (amount) => escape(format_currency(amount, data.currency));
	field.$wrapper.html(`<div style="margin:8px 0;font-size:var(--text-sm)">
		<div>${__("Total payable")}: <strong>${money(data.totals.gross)}</strong></div>
		<div>${__("Total excluding VAT")}: <strong>${money(data.totals.net)}</strong></div>
		<div>${__("VAT")}: <strong>${money(data.totals.vat)}</strong></div>
	</div>`);
	if (item) {
		render_supplier_vat_price_hint(grid);
	}
}

function render_supplier_vat_price_hint(grid) {
	const heading = grid.wrapper.find(
		'.grid-heading-row [data-fieldname="custom_vat_gross_rate"] .static-area'
	);
	heading.find(".supplier-vat-price-info").remove();
	$("<span class='supplier-vat-price-info'></span>")
		.attr({ title: __("Price including VAT"), "aria-label": __("Price including VAT") })
		.css({ display: "inline-flex", "vertical-align": "middle", "margin-left": "4px" })
		.html(frappe.utils.icon("info", "xs"))
		.appendTo(heading);
}

for (const doctype of ["Purchase Invoice", "Payment Request", "Payment Entry"]) {
	const refresh = (frm) => render_supplier_vat_display(frm);
	frappe.ui.form.on(doctype, {
		setup(frm) {
			if (doctype === "Purchase Invoice")
				$(frm.wrapper).on("grid-row-render.supplier-vat-info", (event, row) => {
					if (row.grid.df.fieldname === "items") render_supplier_vat_price_hint(row.grid);
				});
		},
		refresh,
		supplier: refresh,
		party: refresh,
		party_type: refresh,
		grand_total: refresh,
		net_total: refresh,
		currency: refresh,
		paid_amount: refresh,
		received_amount: refresh,
		total_allocated_amount: refresh,
	});
}
for (const doctype of ["Purchase Invoice Item", "Payment Reference", "Payment Entry Reference"]) {
	const refresh = (frm) => render_supplier_vat_display(frm);
	frappe.ui.form.on(doctype, {
		rate: refresh,
		qty: refresh,
		amount: refresh,
		allocated_amount: refresh,
		reference_name: refresh,
		references_remove: refresh,
		payment_reference_remove: refresh,
	});
}
