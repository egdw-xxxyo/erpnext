const recurringPurchaseMethod = "erpnext.buying.doctype.recurring_purchase.recurring_purchase.";

frappe.ui.form.on("Recurring Purchase", {
	setup(frm) {
		frm.set_query("supplier", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0, is_purchase_item: 1 } }));
		frm.set_query("warehouse", "items", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},
	async company(frm) {
		if (!frm.doc.company) return;
		const result = await frappe.db.get_value("Company", frm.doc.company, "default_currency");
		await frm.set_value("currency", result.message.default_currency);
		await frm.set_value("conversion_rate", 1);
		await frm.set_value("taxes_and_charges", "");
	},
	supplier: render_recurring_vat,
	currency: render_recurring_vat,
	refresh(frm) {
		const editable =
			!frm.doc.docstatus &&
			["Чернетка", "Потребує доопрацювання"].includes(frm.doc.workflow_state || "Чернетка");
		for (const field of [
			"title",
			"supplier",
			"company",
			"currency",
			"conversion_rate",
			"valid_from",
			"valid_until",
			"contract_file",
			"items",
			"taxes_and_charges",
			"notes",
		]) {
			frm.set_df_property(field, "read_only", !editable);
		}
		if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Проведено") {
			const today = frappe.datetime.get_today();
			if (today >= frm.doc.valid_from && today <= frm.doc.valid_until) {
				if (frappe.session.user === "Administrator" || frappe.user_roles.includes("Закупівельник")) {
					frm.add_custom_button(
						__("Purchase Invoice"),
						() =>
							frappe.model.open_mapped_doc({
								method: recurringPurchaseMethod + "make_purchase_invoice",
								frm,
							}),
						__("Create")
					);
				}
			} else {
				frm.set_intro(
					__(
						"The recurring purchase is outside its validity period. New invoices are unavailable."
					),
					"orange"
				);
			}
		}
		frm.set_df_property(
			"items",
			"description",
			__(
				"Final prices include 20% VAT for VAT payers. Quantities and prices are defaults, not periodic limits."
			)
		);
		render_recurring_vat(frm);
		render_recurring_purchase(frm);
	},
	before_workflow_action(frm) {
		if (
			!["Повернути на доопрацювання", "Відхилити", "Відкликати на доопрацювання"].includes(
				frm.selected_workflow_action
			)
		)
			return;
		frappe.dom.unfreeze();
		return new Promise((resolve, reject) => {
			let confirmed = false;
			const dialog = new frappe.ui.Dialog({
				title: __("Reason"),
				fields: [{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
				primary_action_label: __("Confirm"),
				primary_action(values) {
					if (!values.reason.trim()) return;
					confirmed = true;
					frm.doc.workflow_action_reason = values.reason.trim();
					dialog.hide();
					resolve();
				},
			});
			dialog.$wrapper.on("hidden.bs.modal", () => {
				if (!confirmed) {
					frm.selected_workflow_action = null;
					reject();
				}
			});
			dialog.show();
		});
	},
});

async function render_recurring_purchase(frm) {
	const name = frm.doc.name;
	let data = { invoices: [], votes: [], approvers: [], users: {} };
	if (!frm.is_new()) {
		const response = await frappe.call({
			method: recurringPurchaseMethod + "get_overview",
			args: { name },
		});
		if (frm.doc.name !== name) return;
		data = response.message;
	}
	render_recurring_route(frm, data);
	const user = (id) => recurring_user_link(data, id);
	const escape = frappe.utils.escape_html;
	const rows = data.invoices
		.map(
			(row) => `<tr>
		<td>${erpnext.entity.doc_link({
			doctype: "Purchase Invoice",
			name: row.name,
		})}</td>
		<td>${user(row.owner)}</td><td>${escape(
				frappe.datetime.str_to_user(row.posting_date)
			)}</td><td>${recurring_invoice_status(row)}</td>
		<td>${format_currency(row.grand_total, row.currency)}</td><td>${
				row.docstatus === 1 ? format_currency(row.outstanding_amount, row.currency) : "—"
			}</td></tr>`
		)
		.join("");
	frm.get_field("invoices_html").$wrapper.html(
		rows
			? `<div class="table-responsive rp-invoices"><table class="table table-bordered"><thead><tr>
		<th>${__("Purchase Invoice")}</th><th>${__("Created by")}</th><th>${__("Date")}</th><th>${__(
					"Status"
			  )}</th><th>${__("Grand Total")}</th><th>${__("Outstanding Amount")}</th>
		</tr></thead><tbody>${rows}</tbody></table></div>`
			: `<p class="text-muted">${__("No invoices have been created from this recurring purchase.")}</p>`
	);
}

frappe.ui.form.on("Recurring Purchase Item", {
	qty: recurring_purchase_row_total,
	rate: recurring_purchase_row_total,
	items_remove: render_recurring_vat,
	rate_excluding_vat(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		return frappe.model.set_value(
			cdt,
			cdn,
			"rate",
			flt(flt(row.rate_excluding_vat) * (frm.__recurring_vat_payer ? 1.2 : 1), precision("rate", row))
		);
	},
});
function recurring_purchase_row_total(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
	return render_recurring_vat(frm);
}

function recurring_user_link(data, id) {
	if (!id) return "";
	return erpnext.entity.doc_link({
		doctype: "User",
		name: id,
		label: data.users[id]?.full_name || frappe.user_info(id)?.fullname || id,
	});
}

function render_recurring_route(frm, data) {
	const state = frm.doc.workflow_state || "Чернетка";
	const rejected = state === "Відхилено" || frm.doc.docstatus === 2;
	const indexes = {
		Чернетка: 0,
		"Потребує доопрацювання": 0,
		"Перевірка підрозділу": 1,
		"Фінальне погодження": 2,
		Погоджено: 3,
		Проведено: 4,
	};
	const current = rejected ? -1 : indexes[state] ?? 0;
	const escape = frappe.utils.escape_html;
	const stages = [
		[__("Preparation"), __("Buyer"), "edit", [frm.doc.owner || frappe.session.user]],
		[
			__("Department Review"),
			__("Department Head"),
			"review",
			[frm.doc.department_approved_by].filter(Boolean),
		],
		[__("Final Approval"), __("Final Approver"), "check", data.votes],
		[__("Posting"), __("Buyer"), "clipboard", [data.submitted_by].filter(Boolean)],
	];
	const steps = stages
		.map(([title, role, icon, users], index) => {
			const done = !rejected && index < current;
			const active = index === current;
			let actor = users.map((id) => recurring_user_link(data, id)).join(", ");
			if (index === 2 && data.automatic && done) {
				role = __("Approved automatically");
				actor = "";
			} else if (index === 2 && data.administrator) role = __("Approved by Administrator");
			else if (index === 2 && (done || active))
				role += ` · ${data.votes.length}/${data.approvers.length}`;
			if (!actor && !(index === 2 && data.automatic && done))
				actor = escape(
					active ? __("In progress") : done ? __("User is not recorded") : __("Not completed yet")
				);
			return `<div class="rp-route-segment"><div class="rp-route-step ${
				done ? "is-complete" : active ? "is-current" : "is-pending"
			}">
   <div class="rp-route-icon">${frappe.utils.icon(
		icon,
		"sm"
   )}</div><div class="rp-route-copy"><div class="rp-route-title">${escape(title)}</div>
   <div class="rp-route-role">${escape(
		role
   )}</div><div class="rp-route-actor">${actor}</div></div></div></div>`;
		})
		.join("");
	const color = rejected
		? "red"
		: current >= 3
		? "green"
		: current > 0
		? "yellow"
		: state === "Потребує доопрацювання"
		? "orange"
		: "blue";
	frm.get_field("approval_route_html").$wrapper.html(`<style>
		.rp-route-card{margin:8px 0 18px;padding:14px 16px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg)}
		.rp-route-card .ent-doc,.rp-invoices .ent-doc{background:transparent;padding:0;border-radius:0}
		.rp-route-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}
		.rp-route-heading{font-size:var(--text-md);font-weight:600;color:var(--heading-color)}
		.rp-route-state{max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
		.rp-route-origin{margin-bottom:14px;font-size:var(--text-sm);color:var(--text-muted)}
		.rp-route-origin a{font-weight:500}
		.rp-route-scroll{overflow:visible;padding:2px 0 4px}
		.rp-route{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));align-items:start;gap:14px;width:100%;min-width:0}
		.rp-route-segment{min-width:0}
		.rp-route-step{display:flex;align-items:flex-start;gap:9px;width:100%;min-width:0}
		.rp-route-icon{display:flex;align-items:center;justify-content:center;width:34px;height:34px;flex:0 0 34px;border:1px solid var(--border-color);border-radius:50%;color:var(--text-muted);background:var(--control-bg)}
		.rp-route-copy{min-width:0;max-width:none}
		.rp-route-title{font-size:var(--text-sm);font-weight:600;line-height:1.25;color:var(--text-color);white-space:normal}
		.rp-route-role{margin-top:2px;font-size:var(--text-xs);line-height:1.25;color:var(--text-muted);white-space:normal;overflow-wrap:anywhere}
		.rp-route-actor{margin-top:4px;overflow:hidden;text-overflow:ellipsis;font-size:var(--text-xs);line-height:1.2;color:var(--text-color);white-space:nowrap}
		.rp-route-actor a{font-weight:500}
		.rp-route-step.is-complete .rp-route-icon{border-color:var(--green-500);background:var(--green-100);color:var(--green-700)}
		.rp-route-step.is-current .rp-route-icon{border-color:var(--blue-500);background:var(--blue-100);color:var(--blue-700);box-shadow:0 0 0 3px var(--blue-50)}
		.rp-route-step.is-pending{opacity:.5}
		.rp-route-card.is-rework .rp-route-step.is-current .rp-route-icon{border-color:var(--orange-500);background:var(--orange-100);color:var(--orange-700);box-shadow:0 0 0 3px var(--orange-50)}
		.rp-route-card.is-rejected .rp-route-icon{border-color:var(--red-300);color:var(--red-500)}
		@media(max-width:767px){.rp-route-card{padding:12px}.rp-route{grid-template-columns:1fr;gap:14px}}</style>
 <div class="rp-route-card ${
		rejected ? "is-rejected" : state === "Потребує доопрацювання" ? "is-rework" : ""
 }">
  <div class="rp-route-head"><div class="rp-route-heading">${__(
		"Approval Route"
  )}</div><span class="indicator-pill no-indicator-dot ${color} rp-route-state">${escape(state)}</span></div>
  <div class="rp-route-scroll"><div class="rp-route">${steps}</div></div></div>`);
}

function recurring_invoice_status(row) {
	const status = row.docstatus === 2 ? "Cancelled" : row.docstatus === 0 ? "Draft" : row.status;
	const colors = {
		Paid: "green",
		Unpaid: "orange",
		Overdue: "red",
		"Partly Paid": "yellow",
		Cancelled: "red",
		Draft: "red",
		Return: "gray",
		"Debit Note Issued": "gray",
		"Internal Transfer": "darkgrey",
	};
	return `<span class="indicator-pill no-indicator-dot ${
		colors[status] || "gray"
	}">${frappe.utils.escape_html(__(status))}</span>`;
}

async function render_recurring_vat(frm) {
	const supplier = frm.doc.supplier;
	const editable =
		!frm.doc.docstatus &&
		["Чернетка", "Потребує доопрацювання"].includes(frm.doc.workflow_state || "Чернетка");
	const { message: party } = supplier
		? await frappe.db.get_value("Supplier", supplier, "custom_is_vat_payer")
		: { message: {} };
	if (frm.doc.supplier !== supplier) return;
	const legacy =
		!frm.is_new() &&
		!frm.doc.supplier_vat_pricing &&
		!["Чернетка", "Потребує доопрацювання"].includes(frm.doc.workflow_state);
	const payer = !legacy && cint(editable ? party?.custom_is_vat_payer : frm.doc.supplier_is_vat_payer);
	frm.__recurring_vat_payer = payer;
	const grid = frm.fields_dict.items.grid;
	grid.update_docfield_property("rate_excluding_vat", "is_virtual", 0);
	grid.update_docfield_property("rate_excluding_vat", "options", "parent.currency");
	grid.update_docfield_property("rate_excluding_vat", "read_only", frm.fields_dict.items.df.read_only);
	grid.update_docfield_property("rate_excluding_vat", "hidden", !payer);
	const explanation = __("Final unit price: includes 20% VAT for VAT payers; no VAT for other suppliers.");
	grid.update_docfield_property("rate", "description", legacy ? "" : explanation);
	for (const row of frm.doc.items || []) row.rate_excluding_vat = flt(flt(row.rate) / (payer ? 1.2 : 1), 6);
	if (frm.__recurring_vat_visible !== Boolean(payer)) {
		grid.reset_grid();
		frm.__recurring_vat_visible = Boolean(payer);
	}
	frm.refresh_field("items");
	if (!legacy) {
		grid.wrapper.find('[data-fieldname="rate"]').attr("title", explanation);
		const header = grid.wrapper.find('.grid-heading-row [data-fieldname="rate"] .static-area');
		if (!header.find(".rp-vat-info").length)
			header.append(` <span class="rp-vat-info">${frappe.utils.icon("info", "xs")}</span>`);
	}
	const precision = frappe.meta.get_field_precision(frm.get_docfield("grand_total"), frm.doc);
	const gross = flt(
		(frm.doc.items || []).reduce((total, row) => total + flt(row.qty) * flt(row.rate), 0),
		precision
	);
	const vat = payer ? flt(gross - gross / 1.2, precision) : 0;
	if (editable) {
		frm.doc.grand_total = gross;
		frm.doc.net_total = gross - vat;
		frm.refresh_fields(["grand_total", "net_total"]);
	}
	const money = (value) => frappe.utils.escape_html(format_currency(value, frm.doc.currency));
	frm.fields_dict.vat_totals_html.$wrapper.html(
		legacy
			? `<p class="text-muted">${__(
					"This approved document retains its original tax template and amounts."
			  )}</p>`
			: `<div>${__("VAT")}: <strong>${money(
					payer ? frm.doc.grand_total - frm.doc.net_total : 0
			  )}</strong></div><small class="text-muted">${
					payer ? __("VAT calculation uses 20% for VAT payers.") : __("Without VAT")
			  }</small>`
	);
}
