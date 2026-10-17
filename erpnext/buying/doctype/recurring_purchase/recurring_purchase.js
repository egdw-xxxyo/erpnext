const recurringPurchaseMethod = "erpnext.buying.doctype.recurring_purchase.recurring_purchase.";

frappe.ui.form.on("Recurring Purchase", {
	setup(frm) {
		frm.set_query("supplier", () => ({ filters: { disabled: 0 } }));
		frm.set_query("item_code", "items", () => ({ filters: { disabled: 0, is_purchase_item: 1 } }));
		frm.set_query("warehouse", "items", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("taxes_and_charges", () => ({ filters: { company: frm.doc.company, disabled: 0 } }));
	},
	async company(frm) {
		if (!frm.doc.company) return;
		const result = await frappe.db.get_value("Company", frm.doc.company, "default_currency");
		await frm.set_value("currency", result.message.default_currency);
		await frm.set_value("conversion_rate", 1);
		await frm.set_value("taxes_and_charges", "");
	},
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
				"Prices and VAT follow the selected purchase tax template. Quantities and prices are defaults, not periodic limits."
			)
		);
		if (!frm.is_new()) render_recurring_purchase(frm);
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
	const { message: data } = await frappe.call({
		method: recurringPurchaseMethod + "get_overview",
		args: { name },
	});
	if (frm.doc.name !== name) return;
	const state = frm.doc.workflow_state;
	const stages = [
		[__("Preparation"), "edit", frm.doc.owner, true],
		[
			__("Department Review"),
			"users",
			frm.doc.department_approved_by,
			Boolean(frm.doc.department_approved_by),
		],
		[__("Final Approval"), "check", data.votes, ["Погоджено", "Проведено"].includes(state)],
		[__("Submit"), "file-text-o", null, frm.doc.docstatus === 1],
	];
	frm.get_field("approval_route_html").$wrapper.html(
		`<div class="row" style="padding:16px 0">${stages
			.map(
				([label, icon, user, done], index) => `
		<div class="col-sm-3"><i class="fa fa-${icon} ${
					done ? "text-success" : "text-muted"
				}"></i> <strong>${label}</strong>
		<div>${
			index === 2 && data.automatic && done
				? __("Approved automatically")
				: Array.isArray(user)
				? user.map((u) => erpnext.entity.user(u, { size: 18 })).join(" ")
				: user
				? erpnext.entity.user(user, { size: 18 })
				: ""
		}</div>
		${
			index === 2 && !data.automatic
				? `<small>${
						data.administrator
							? __("Approved by Administrator")
							: `${data.votes.length}/${data.approvers.length}`
				  }</small>`
				: ""
		}</div>`
			)
			.join("")}</div>`
	);
	const escape = frappe.utils.escape_html;
	const rows = data.invoices
		.map(
			(row) => `<tr>
		<td>${erpnext.entity.html({
			name: row.name,
			icon: "file-text-o",
			route: ["Form", "Purchase Invoice", row.name],
		})}</td>
		<td>${escape(frappe.datetime.str_to_user(row.posting_date))}</td><td>${escape(__(row.status))}</td>
		<td>${format_currency(row.grand_total, row.currency)}</td><td>${
				row.docstatus === 1 ? format_currency(row.outstanding_amount, row.currency) : "—"
			}</td></tr>`
		)
		.join("");
	frm.get_field("invoices_html").$wrapper.html(
		rows
			? `<div class="table-responsive"><table class="table table-bordered"><thead><tr>
		<th>${__("Purchase Invoice")}</th><th>${__("Date")}</th><th>${__("Status")}</th><th>${__(
					"Grand Total"
			  )}</th><th>${__("Outstanding Amount")}</th>
		</tr></thead><tbody>${rows}</tbody></table></div>`
			: `<p class="text-muted">${__("No invoices have been created from this recurring purchase.")}</p>`
	);
}

frappe.ui.form.on("Recurring Purchase Item", {
	qty: recurring_purchase_row_total,
	rate: recurring_purchase_row_total,
});
function recurring_purchase_row_total(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
}
