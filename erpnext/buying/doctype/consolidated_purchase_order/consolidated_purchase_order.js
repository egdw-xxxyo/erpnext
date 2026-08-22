frappe.ui.form.on("Consolidated Purchase Order", {
	setup(frm) {
		frappe.meta.get_docfield(
			"Consolidated Purchase Supplier Invoice",
			"invoice_document",
			frm.doc.name
		).formatter = (value, df, options, doc) => {
			const file_name = value || get_file_name(doc.invoice_pdf);
			if (!file_name || !doc.invoice_pdf) return "";
			return `<a href="${frappe.utils.escape_html(
				doc.invoice_pdf
			)}" target="_blank">${frappe.utils.escape_html(file_name)}</a>`;
		};
		frm.set_query("supplier", "supplier_invoices", () => ({
			filters: {
				name: ["in", get_order_suppliers(frm)],
			},
		}));
	},

	refresh(frm) {
		set_procurement_status_indicator(frm);
		setTimeout(() => set_procurement_status_indicator(frm), 0);
		frm.fields_dict.supplier_invoices.grid.update_docfield_property("invoice_pdf", "options", {
			restrictions: { allowed_file_types: [".pdf"] },
			allow_web_link: false,
		});
		frm.fields_dict.supplier_invoices.grid.update_docfield_property("supplier", "hidden", 0);
		frm.fields_dict.supplier_invoices.grid.update_docfield_property("supplier", "reqd", 1);
		set_table_row_number_labels(frm);
		setTimeout(() => set_table_row_number_labels(frm), 100);
		frm.trigger("render_approval_route");
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

	workflow_state(frm) {
		frm.trigger("render_approval_route");
	},

	procurement_completion_status(frm) {
		set_procurement_status_indicator(frm);
	},

	render_approval_route(frm) {
		const field = frm.get_field("approval_route_html");
		if (!field) return;
		if (frm.is_new()) {
			render_approval_route(frm, field, {});
			return;
		}

		frappe
			.call({
				method: "erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_approval_route_summary",
				args: { source_name: frm.doc.name },
			})
			.then((response) => render_approval_route(frm, field, response.message || {}));
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
				method: "erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_purchase_order_summary",
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
						<td>${render_status_badge(
							row.payment_complete ? __("Payment completed") : __("Payment not completed"),
							row.payment_complete ? "green" : "gray"
						)}</td>
						<td>${render_status_badge(
							row.fiscal_receipt_added ? __("Added") : __("Fiscal receipt missing"),
							row.fiscal_receipt_added ? "green" : "gray"
						)}</td>
						<td>${render_purchase_receipts(row.purchase_receipts || [])}</td>
					</tr>`
					)
					.join("");
				field.$wrapper
					.html(`<div class="table-responsive"><table class="table table-bordered table-sm">
				<thead><tr><th>${__("Purchase Order")}</th><th>${__("Supplier")}</th><th class="text-right">${__(
					"Grand Total"
				)}</th><th class="text-right">${__("Billed")}</th><th>${__(
					"Payment Completed"
				)}</th><th>${__("Fiscal Receipt")}</th><th>${__(
					"Purchase Receipt"
				)}</th></tr></thead><tbody>${body}</tbody></table></div>`);
			});
	},
});

function render_approval_route(frm, field, route_data) {
	const invoice_count = cint(route_data.payment_invoice_count ?? frm.doc.payment_invoice_count);
	const receipt_count = cint(route_data.payment_receipt_count ?? frm.doc.payment_receipt_count);
	const has_submitted_invoice = cint(route_data.submitted_invoice_count) > 0;
	const external_payment = Boolean(route_data.external_payment);
	const payment_complete =
		external_payment || (has_submitted_invoice && receipt_count >= invoice_count);
	const purchase_receipt_complete = Boolean(route_data.purchase_receipt_complete);
	const final_approval_count = cint(route_data.final_approval_count);
	const final_approval_required = cint(route_data.final_approval_required) || 2;
	const final_approval_automatic = Boolean(route_data.final_approval_automatic);
	const stages = [
		{ key: "preparation", title: __("Preparation"), role: __("Buyer"), icon: "edit" },
		{
			key: "department_review",
			title: __("Department Review"),
			role: __("Department Head"),
			icon: "review",
		},
		{
			key: "final_approval",
			title: __("Final Approval"),
			role: __("Final Approver"),
			icon: "check",
		},
		{ key: "posting", title: __("Posting"), role: __("Buyer"), icon: "clipboard" },
		{
			key: "payment",
			title: __("Payment"),
			role: __("Treasurer"),
			icon: "es-line-payments",
		},
		{
			key: "receipt",
			title: __("Goods Receipt"),
			role: __("Warehouse Manager"),
			icon: "clipboard",
		},
	];
	const state = frm.doc.workflow_state || "Чернетка";
	const state_indexes = {
		Чернетка: 0,
		"Потребує доопрацювання": 0,
		"Перевірка підрозділу": 1,
		"Фінальне погодження": 2,
		Погоджено: 3,
		Проведено: 3,
	};
	const current_index = state_indexes[state] ?? 0;
	const is_rework = state === "Потребує доопрацювання";
	const is_rejected = state === "Відхилено";
	const state_class = is_rejected ? "is-rejected" : is_rework ? "is-rework" : "";

	const steps = stages
		.map((stage, index) => {
			const is_payment = stage.key === "payment";
			const is_receipt = stage.key === "receipt";
			const is_posting = stage.key === "posting";
			const is_final_approval = stage.key === "final_approval";
			const completed = is_receipt
				? purchase_receipt_complete
				: is_payment
				? payment_complete
				: !is_rejected &&
				  (index < current_index || (is_posting && frm.doc.docstatus === 1 && has_submitted_invoice));
			const current = is_receipt
				? payment_complete && !purchase_receipt_complete
				: is_payment
				? frm.doc.docstatus === 1 && has_submitted_invoice && !payment_complete
				: !is_rejected &&
				  ((frm.doc.docstatus !== 1 && index === current_index) ||
					(is_posting && frm.doc.docstatus === 1 && !has_submitted_invoice));
			const status_class = completed ? "is-complete" : current ? "is-current" : "is-pending";
			const actors = is_receipt
				? route_data.receipt_actors || []
				: is_payment
				? external_payment && route_data.external_payer
					? [route_data.external_payer]
					: route_data.payment_actors || []
				: is_final_approval && (route_data.final_approved_users || []).length
				? route_data.final_approved_users
				: route_data.stage_actors?.[stage.key]
				? [route_data.stage_actors[stage.key]]
				: current
				? route_data.current_assignees || []
				: [];
			let actor_text = get_route_actor_text(actors, completed, current);
			let role_text = stage.role;
			if (is_final_approval && final_approval_automatic && completed) {
				role_text = __("Approved automatically");
				actor_text = "";
			} else if (is_final_approval && (current || completed)) {
				role_text = `${stage.role} · ${final_approval_count}/${final_approval_required}`;
			} else if (is_posting && frm.doc.docstatus === 1 && !has_submitted_invoice) {
				role_text = __("Submitted, invoice not created");
			} else if (is_payment && external_payment) {
				role_text = __("Payment was made at the expense of:");
			} else if (is_payment && has_submitted_invoice) {
				role_text = `${stage.role} · ${receipt_count}/${invoice_count} ${__("paid")}`;
			} else if (is_receipt && current) {
				role_text = `${stage.role} · ${__("Awaiting Purchase Receipt")}`;
			}
			const actor_html =
				is_payment && external_payment && route_data.external_payer
					? render_user_link(route_data.external_payer)
					: frappe.utils.escape_html(actor_text);
			return `<div class="cpo-route-segment">
				<div class="cpo-route-step ${status_class}">
					<div class="cpo-route-icon">${frappe.utils.icon(stage.icon, "sm")}</div>
					<div class="cpo-route-copy">
						<div class="cpo-route-title">${frappe.utils.escape_html(stage.title)}</div>
						<div class="cpo-route-role">${frappe.utils.escape_html(role_text)}</div>
						<div class="cpo-route-actor" title="${frappe.utils.escape_html(
							actor_text
						)}">${actor_html}</div>
					</div>
				</div>
			</div>`;
		})
		.join("");

	const origin = render_material_request_origin(route_data.material_requests || []);
	field.$wrapper.html(`<style>
		.cpo-route-card{margin:8px 0 18px;padding:14px 16px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg)}
		.cpo-route-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}
		.cpo-route-heading{font-size:var(--text-md);font-weight:600;color:var(--heading-color)}
		.cpo-route-state{max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
		.cpo-route-origin{margin-bottom:14px;font-size:var(--text-sm);color:var(--text-muted)}
		.cpo-route-origin a{font-weight:500}
		.cpo-route-scroll{overflow:visible;padding:2px 0 4px}
		.cpo-route{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));align-items:start;gap:14px;width:100%;min-width:0}
		.cpo-route-segment{min-width:0}
		.cpo-route-step{display:flex;align-items:flex-start;gap:9px;width:100%;min-width:0}
		.cpo-route-icon{display:flex;align-items:center;justify-content:center;width:34px;height:34px;flex:0 0 34px;border:1px solid var(--border-color);border-radius:50%;color:var(--text-muted);background:var(--control-bg)}
		.cpo-route-copy{min-width:0;max-width:none}
		.cpo-route-title{font-size:var(--text-sm);font-weight:600;line-height:1.25;color:var(--text-color);white-space:normal}
		.cpo-route-role{margin-top:2px;font-size:var(--text-xs);line-height:1.25;color:var(--text-muted);white-space:normal;overflow-wrap:anywhere}
		.cpo-route-actor{margin-top:4px;overflow:hidden;text-overflow:ellipsis;font-size:var(--text-xs);line-height:1.2;color:var(--text-color);white-space:nowrap}
		.cpo-route-actor a{font-weight:500}
		.cpo-route-step.is-complete .cpo-route-icon{border-color:var(--green-500);background:var(--green-100);color:var(--green-700)}
		.cpo-route-step.is-current .cpo-route-icon{border-color:var(--blue-500);background:var(--blue-100);color:var(--blue-700);box-shadow:0 0 0 3px var(--blue-50)}
		.cpo-route-step.is-pending{opacity:.5}
		.cpo-route-card.is-rework .cpo-route-step.is-current .cpo-route-icon{border-color:var(--orange-500);background:var(--orange-100);color:var(--orange-700);box-shadow:0 0 0 3px var(--orange-50)}
		.cpo-route-card.is-rejected .cpo-route-icon{border-color:var(--red-300);color:var(--red-500)}
		@media(max-width:767px){.cpo-route-card{padding:12px}.cpo-route{grid-template-columns:1fr;gap:14px}}
	</style>
	<div class="cpo-route-card ${state_class}">
		<div class="cpo-route-head">
			<div class="cpo-route-heading">${__("Approval Route")}</div>
			<span class="indicator-pill no-indicator-dot ${get_route_indicator_color(state)} cpo-route-state">${frappe.utils.escape_html(
				state
			)}</span>
		</div>
		${origin}
		<div class="cpo-route-scroll"><div class="cpo-route">${steps}</div></div>
	</div>`);
}

function set_procurement_status_indicator(frm) {
	const status = frm.doc.procurement_completion_status;
	if (!status) return;
	const color = erpnext.buying.get_procurement_status_color(status);
	frm.page.set_indicator(__(status), color);
}

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

function render_status_badge(label, colour) {
	return `<span class="indicator-pill no-indicator-dot ${colour}">${frappe.utils.escape_html(
		label
	)}</span>`;
}

function render_purchase_receipts(receipts) {
	if (!receipts.length) {
		return render_status_badge(__("Not created"), "gray");
	}
	return receipts
		.map((receipt) => {
			const link = `<a href="/app/purchase-receipt/${encodeURIComponent(
				receipt.name
			)}">${frappe.utils.escape_html(receipt.name)}</a>`;
			const status = render_status_badge(
				__(receipt.status || "Submitted"),
				receipt.status === "Completed" ? "green" : "blue"
			);
			return `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">${link}${status}</div>`;
		})
		.join("");
}

function get_route_indicator_color(state) {
	if (state === "Проведено" || state === "Погоджено") return "green";
	if (state === "Відхилено") return "red";
	if (state === "Потребує доопрацювання") return "orange";
	if (state === "Перевірка підрозділу" || state === "Фінальне погодження") return "yellow";
	return "blue";
}

function render_material_request_origin(material_requests) {
	if (!material_requests.length) {
		return `<div class="cpo-route-origin">${__("Source Material Request is not specified.")}</div>`;
	}

	const requests = material_requests
		.map((request) => {
			const link = `<a href="/app/material-request/${encodeURIComponent(request.name)}">${frappe.utils.escape_html(
				request.name
			)}</a>`;
			const creator = frappe.utils.escape_html(request.created_by?.full_name || request.owner || "");
			return `${link} · ${__("Created by")}: ${creator}`;
		})
		.join("; ");
	return `<div class="cpo-route-origin"><span>${__("Source Material Request")}:</span> ${requests}</div>`;
}

function get_route_actor_text(actors, completed, current) {
	const names = actors.map((actor) => actor.full_name || actor.user).filter(Boolean);
	if (names.length) {
		return names.join(", ");
	}
	if (current) return __("In progress");
	if (completed) return __("User is not recorded");
	return __("Not completed yet");
}

function render_user_link(user) {
	const user_id = user.user || "";
	const label = user.full_name || user_id;
	return `<a href="/app/user/${encodeURIComponent(user_id)}">${frappe.utils.escape_html(label)}</a>`;
}
