// The saved rate stays the final payable unit price. Net price and VAT are derived only.
frappe.provide("erpnext.procurement_vat");

erpnext.procurement_vat.calculate = function (items, suppliers, precision = 2) {
	const groups = Object.create(null);
	for (const row of items) {
		const key = row.supplier || "";
		const group = (groups[key] ||= { gross: 0, vat: 0 });
		group.gross += flt(row.qty) * flt(row.rate);
	}
	const gross = flt(
		Object.values(groups).reduce((sum, group) => sum + group.gross, 0),
		precision
	);
	for (const [supplier, group] of Object.entries(groups)) {
		group.gross = flt(group.gross, precision);
		group.vat = cint(suppliers[supplier]?.custom_is_vat_payer)
			? flt(group.gross - group.gross / 1.2, precision)
			: 0;
	}
	const vat = flt(
		Object.values(groups).reduce((sum, group) => sum + group.vat, 0),
		precision
	);
	return { groups, gross, vat, net: flt(gross - vat, precision) };
};

async function cpo_vat_suppliers(frm, reload = false) {
	if (reload) frm.__vat_suppliers = Object.create(null);
	frm.__vat_suppliers ||= Object.create(null);
	const names = [
		...new Set(
			[
				...(frm.doc.items || []).map((row) => row.supplier),
				...(frm.doc.supplier_invoices || []).map((row) => row.supplier),
				frm.doc.set_supplier,
			].filter(Boolean)
		),
	];
	const missing = names.filter((name) => !frm.__vat_suppliers[name]);
	if (missing.length) {
		const suppliers = await frappe.db.get_list("Supplier", {
			filters: { name: ["in", missing] },
			fields: ["name", "supplier_name", "custom_is_vat_payer"],
			limit: missing.length,
		});
		for (const supplier of suppliers) frm.__vat_suppliers[supplier.name] = supplier;
		if (missing.some((name) => !frm.__vat_suppliers[name])) {
			frappe.throw(__("Could not read supplier VAT status. Check Supplier access permissions."));
		}
	}
	return frm.__vat_suppliers;
}

async function render_cpo_vat(frm, reload = false) {
	if (!frm.fields_dict.custom_vat_totals) return;
	const suppliers = await cpo_vat_suppliers(frm, reload);
	const items = frm.doc.items || [];
	const names = [...items, ...(frm.doc.supplier_invoices || []), { supplier: frm.doc.set_supplier }];
	const visible = names.some((row) => cint(suppliers[row.supplier]?.custom_is_vat_payer));
	const grid = frm.fields_dict.items.grid;
	const payment = frm.fields_dict.payment_receipts_progress;
	const billed = frm.fields_dict.per_billed;
	if (payment && billed) payment.$wrapper.insertAfter(billed.$wrapper);
	// Frappe makes virtual fields read-only. This grid-local input writes only `rate`;
	// server metadata stays virtual, so the derived value is never stored in the DB.
	grid.update_docfield_property("custom_rate_excluding_vat", "is_virtual", 0);
	grid.update_docfield_property("custom_rate_excluding_vat", "options", "parent.currency");
	if (frm.__vat_column_visible !== visible) {
		grid.update_docfield_property("custom_rate_excluding_vat", "hidden", visible ? 0 : 1);
		grid.reset_grid();
		frm.__vat_column_visible = visible;
	}
	const explanation = __("Final unit price: includes 20% VAT for VAT payers; no VAT for other suppliers.");
	grid.update_docfield_property("rate", "label", __("Price"));
	grid.update_docfield_property("custom_rate_excluding_vat", "label", __("Price excluding VAT"));
	grid.update_docfield_property("rate", "description", explanation);
	for (const row of items) {
		row.custom_rate_excluding_vat = flt(
			flt(row.rate) / (cint(suppliers[row.supplier]?.custom_is_vat_payer) ? 1.2 : 1),
			6
		);
	}
	frm.refresh_field("items");
	grid.wrapper.find('[data-fieldname="rate"]').attr("title", explanation);
	render_cpo_price_info(grid);
	frm.set_df_property("grand_total", "label", __("Total payable"));
	const precision = frappe.meta.get_field_precision(frm.get_docfield("grand_total"), frm.doc);
	const totals = erpnext.procurement_vat.calculate(items, suppliers, precision);
	const escape = frappe.utils.escape_html;
	const money = (value) => escape(format_currency(value, frm.doc.currency));
	const breakdown = Object.entries(totals.groups)
		.map(([supplier, group]) => {
			const identity = supplier
				? erpnext.entity.html({
						name: suppliers[supplier]?.supplier_name || supplier,
						key: supplier,
						icon: "fa fa-building",
						route: ["Form", "Supplier", supplier],
				  })
				: escape(__("Not specified"));
			return `<div class="d-flex justify-content-between" style="gap:16px">${identity}<span>${
				cint(suppliers[supplier]?.custom_is_vat_payer) ? money(group.vat) : escape(__("Without VAT"))
			}</span></div>`;
		})
		.join("");
	frm.fields_dict.custom_vat_totals.$wrapper.html(`
		<div class="cpo-vat-summary">
			<div>${escape(__("Total excluding VAT"))}: <strong>${money(totals.net)}</strong></div>
			<div class="cpo-vat-trigger" tabindex="0" role="button" aria-label="${escape(__("VAT breakdown"))}">
				${escape(__("VAT"))} <i class="fa fa-info-circle" aria-hidden="true"></i>: <strong>${money(
		totals.vat
	)}</strong>
				<div class="cpo-vat-breakdown">${breakdown}</div>
			</div>
			<small class="text-muted">${escape(__("VAT calculation uses 20% for VAT payers."))}</small>
		</div>
		<style>
			.cpo-vat-trigger{position:relative;width:fit-content;cursor:help}
			.cpo-vat-breakdown{display:none;position:absolute;bottom:100%;left:0;z-index:20;
				min-width:300px;max-width:85vw;padding:12px;background:var(--card-bg);border:1px solid var(--border-color);
				border-radius:8px;box-shadow:var(--shadow-sm)}
			.cpo-vat-trigger:hover .cpo-vat-breakdown,.cpo-vat-trigger:focus-within .cpo-vat-breakdown{display:block}
		</style>`);
}

function render_cpo_price_info(grid) {
	const explanation = __("Final unit price: includes 20% VAT for VAT payers; no VAT for other suppliers.");
	const heading = grid.wrapper.find('.grid-heading-row [data-fieldname="rate"]');
	heading.attr("title", explanation).find(".cpo-price-info").remove();
	$("<span class='cpo-price-info'></span>")
		.attr({ title: explanation, "aria-label": explanation })
		.css({ display: "inline-flex", "vertical-align": "middle", "margin-left": "4px" })
		.html(frappe.utils.icon("info", "xs"))
		.appendTo(heading.find(".static-area"));
}

frappe.ui.form.on("Consolidated Purchase Order", {
	setup(frm) {
		$(frm.wrapper).on("grid-row-render.price-info", (event, row) => {
			if (row.grid.df.fieldname === "items") render_cpo_price_info(row.grid);
		});
	},
	refresh(frm) {
		return render_cpo_vat(frm, true);
	},
	render_supplier_contacts(frm) {
		return render_cpo_vat(frm);
	},
	set_supplier(frm) {
		return render_cpo_vat(frm);
	},
});
frappe.ui.form.on("Consolidated Purchase Order Item", {
	supplier: render_cpo_vat_row,
	rate: render_cpo_vat_row,
	qty: render_cpo_vat_row,
	async items_remove(frm) {
		await frm.set_value(
			"grand_total",
			(frm.doc.items || []).reduce((sum, row) => sum + flt(row.qty) * flt(row.rate), 0)
		);
		await frm.set_value(
			"total_qty",
			(frm.doc.items || []).reduce((sum, row) => sum + flt(row.qty), 0)
		);
		return render_cpo_vat(frm);
	},
	async custom_rate_excluding_vat(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const value = flt(row.custom_rate_excluding_vat);
		const suppliers = await cpo_vat_suppliers(frm);
		await frappe.model.set_value(
			cdt,
			cdn,
			"rate",
			flt(
				value * (cint(suppliers[row.supplier]?.custom_is_vat_payer) ? 1.2 : 1),
				frappe.meta.get_field_precision(frappe.meta.get_docfield(cdt, "rate", frm.doc.name), row)
			)
		);
		return render_cpo_vat(frm);
	},
});
frappe.ui.form.on("Consolidated Purchase Supplier Invoice", {
	supplier: render_cpo_vat_row,
	supplier_invoices_remove: render_cpo_vat_row,
});
function render_cpo_vat_row(frm) {
	return render_cpo_vat(frm);
}
