(() => {
	const guide = erpnext.helper_guide;
	if (!guide || guide.has_rule("procurement_stock_warehouse")) return;

	const { visible, can_write, add_row_step, button_step, menu_labels, custom_button, status_step } = guide;
	const invoice_options =
		"erpnext.buying.doctype.consolidated_purchase_order.consolidated_purchase_order.get_purchase_invoice_options";
	const buyer_actions = {
		Чернетка: "Подати на перевірку підрозділу",
		"Потребує доопрацювання": "Подати повторно",
		Погоджено: "Провести",
	};
	const approval_actions = ["Погодити", "Погодити за всіх CEO", "Повернути на доопрацювання", "Відхилити"];
	const skipped_invoice_steps = new Map();

	function order_state(doc) {
		return doc.workflow_state || "Чернетка";
	}

	function is_order_buyer(doc) {
		const user = frappe.session.user;
		const buyer = doc.initiator_user || doc.owner || (doc.__islocal && user);
		return user === "Administrator" || (buyer === user && frappe.user.has_role("Закупівельник"));
	}

	function status(frm, message, field, selector) {
		return status_step(
			frm,
			message,
			field,
			selector,
			undefined,
			frm.body.find(".procurement-form-status")[0]
		);
	}

	function route(frm, message, stage) {
		const selector = stage ? '[data-procurement-stage="' + stage + '"]' : ".cpo-route-card";
		return status(frm, message, frm.get_field("approval_route_html"), selector);
	}

	function current(frm, stage) {
		return Boolean(
			frm
				.get_field("approval_route_html")
				?.$wrapper.find('[data-procurement-stage="' + stage + '"].is-current').length
		);
	}

	function waits_at(stage, filter = () => true) {
		return async (frm, doc, { hint }) => {
			const data = await frm.procurement_route_request;
			if (frm.doc === doc && current(frm, stage) && filter(data, doc)) {
				return route(frm, __(hint), stage);
			}
		};
	}

	function create_invoice_button(frm) {
		const button = custom_button(frm, "Purchase Invoice", "Create");
		if (current(frm, "posting") && visible(button) && frappe.model.can_create("Purchase Invoice"))
			return button;
	}

	function invoice_info(name, context) {
		if (!context.has("invoice_options")) {
			context.set("invoice_options", frappe.xcall(invoice_options, { source_name: name }));
		}
		return context.get("invoice_options");
	}

	function get_buyer_context(frm, doc) {
		const state = order_state(doc);
		const action = buyer_actions[state];
		const can_act = action && menu_labels(frm.page.actions).includes(__(action));
		return {
			action,
			can_act,
			buyer: action && (can_act || is_order_buyer(doc)),
			stage: state === "Погоджено" ? "posting" : "preparation",
		};
	}

	const rules = {
		request_create(frm, doc, { hint }) {
			const label = ["Create another consolidated purchase order", "Consolidated Purchase Order"].find(
				(action) => frm.custom_buttons[__(action)]
			);
			if (label) return button_step(custom_button(frm, label, "Create"), __(hint, [__(label)]));
		},
		request_links(frm, doc, { hint }) {
			const field = frm.get_field("custom_consolidated_purchase_orders_html");
			if (field?.$wrapper.find("tbody a").length) return status(frm, __(hint), field, "table");
		},
		async stock_warehouse(frm, doc, { hint }) {
			const field = frm.get_field("items");
			const rows = (doc.items || []).filter((row) => row.item_code && !row.warehouse);
			if (!can_write(field) || !field.grid?.is_editable() || !rows.length) return;
			const codes = [...new Set(rows.map((row) => row.item_code))];
			const stock = await frappe.xcall("frappe.client.get_list", {
				doctype: "Item",
				fields: ["name"],
				filters: { name: ["in", codes], is_stock_item: 1 },
				limit_page_length: codes.length,
			});
			if (frm.doc !== doc) return;
			const names = new Set((stock || []).map(({ name }) => name));
			const row = rows.find((entry) => !entry.warehouse && names.has(entry.item_code));
			if (row) {
				const df =
					field.grid.get_row(row.name)?.docfields?.find((df) => df.fieldname === "warehouse") ||
					field.grid.docfields?.find((df) => df.fieldname === "warehouse");
				if (
					df &&
					!df.hidden_due_to_dependency &&
					frappe.perm.get_field_display_status(df, row, frm.perm) === "Write"
				) {
					return guide.row_step(field, row, df, __(hint));
				}
			}
		},
		initiator(frm, doc, { hint }) {
			if (!doc.request_initiator_user) {
				return button_step(frm.body.find(".procurement-initiator-button")[0], __(hint));
			}
		},
		optional_invoice(frm, doc, { hint }) {
			const field = frm.get_field("supplier_invoices");
			const state = order_state(doc);
			const skipped = skipped_invoice_steps.get(doc.name);
			if (
				!doc.request_initiator_user ||
				!get_buyer_context(frm, doc).buyer ||
				skipped?.has(state) ||
				(doc.supplier_invoices || []).some((row) => row.invoice_pdf) ||
				!can_write(field) ||
				!field.grid?.is_editable()
			)
				return;
			return {
				...add_row_step(field, __(hint)),
				skip() {
					const states = skipped || new Set();
					states.add(state);
					skipped_invoice_steps.set(doc.name, states);
				},
			};
		},
		route: (frm, doc, { hint }) => route(frm, __(hint)),
		async complete(frm, doc, { hint }) {
			const data = await frm.procurement_route_request;
			if (frm.doc !== doc) return;
			const payment_complete =
				data?.external_payment ||
				(data?.payment_invoice_count > 0 && data.payment_receipt_count >= data.payment_invoice_count);
			if (
				data
					? data.purchase_receipt_complete && payment_complete
					: doc.procurement_completion_status === "Завершено"
			) {
				return route(frm, __(hint), "receipt");
			}
		},
		async review(frm, doc, { hint }) {
			const data = await frm.procurement_route_request;
			if (frm.doc !== doc) return;
			let labels = menu_labels(frm.page.actions);
			const final = doc.workflow_state === "Фінальне погодження";
			if (final && frappe.session.user !== "Administrator") {
				const user = frappe.session.user;
				const can_vote =
					data?.final_approvers?.some((approver) => approver.user === user) &&
					!data.final_approved_users?.some((approver) => approver.user === user);
				if (!can_vote) labels = labels.filter((label) => label !== __("Погодити"));
			}
			const decisions = approval_actions.filter((action) => labels.includes(__(action)));
			if (!decisions.length) return;
			const message = __(hint);
			const button = frm.page.actions_btn_group.find("button")[0];
			return {
				...(button_step(button, message) ||
					route(frm, message, final ? "final_approval" : "department_review")),
				decisions: decisions.map((action) =>
					action === "Погодити" ? __(action) : __("{0} (a reason is required)", [__(action)])
				),
			};
		},
		buyer_save(frm, doc, { hint }) {
			const { action, buyer, stage } = get_buyer_context(frm, doc);
			if (buyer && (frm.is_new() || frm.is_dirty())) return route(frm, __(hint, [__(action)]), stage);
		},
		buyer_actions(frm, doc, { hint }) {
			const { action, can_act } = get_buyer_context(frm, doc);
			if (can_act)
				return button_step(frm.page.actions_btn_group.find("button")[0], __(hint, [__(action)]));
		},
		buyer_route(frm, doc, { hint }) {
			const { action, buyer, stage } = get_buyer_context(frm, doc);
			if (buyer) return route(frm, __(hint, [__(action)]), stage);
		},
		async create_invoice(frm, doc, { hint }, context) {
			const button = create_invoice_button(frm);
			if (!button) return;
			const options = await invoice_info(doc.name, context);
			if (frm.doc === doc && options?.eligible_orders?.length) return button_step(button, __(hint));
		},
		async missing_invoice(frm, doc, { hint }, context) {
			const field = frm.get_field("supplier_invoices");
			if (!create_invoice_button(frm) || !can_write(field) || !field.grid?.is_editable()) return;
			const options = await invoice_info(doc.name, context);
			if (frm.doc === doc && options?.missing_suppliers?.length) return add_row_step(field, __(hint));
		},
		async attach_delivery_note(frm, doc, { hint }) {
			const data = await frm.procurement_route_request;
			if (frm.doc === doc && data?.missing_delivery_note_suppliers?.length && current(frm, "receipt")) {
				return button_step(custom_button(frm, "Attach delivery note"), __(hint));
			}
		},
		payment_route(frm, doc, { hint }) {
			const invoices = frm.procurement_invoice_links;
			if (
				current(frm, "payment") &&
				frappe.user.has_role("Payments: Казначей") &&
				invoices?.source_name === doc.name &&
				invoices.invoices.some((invoice) => invoice.docstatus === 1)
			) {
				return status(
					frm,
					__(hint),
					frm.get_field("custom_procurement_links"),
					'[data-procurement-doctype="Purchase Invoice"]'
				);
			}
		},
		wait_preparation: waits_at("preparation"),
		wait_department: waits_at("department_review"),
		wait_final: waits_at("final_approval"),
		wait_post: waits_at("posting"),
		wait_invoices: waits_at("posting"),
		wait_payment: waits_at("payment"),
		wait_warehouse: waits_at("receipt", (data) => !data?.warehouse_receipt_complete),
		wait_delivery_notes: waits_at("receipt", (data) => data?.warehouse_receipt_complete),
	};

	for (const [name, resolve] of Object.entries(rules)) guide.register_rule("procurement_" + name, resolve);
	$(document).on("rename.procurement-assistant", (_, doctype, old_name, new_name) => {
		if (doctype !== "Consolidated Purchase Order" || !skipped_invoice_steps.has(old_name)) return;
		skipped_invoice_steps.set(new_name, skipped_invoice_steps.get(old_name));
		skipped_invoice_steps.delete(old_name);
	});
})();
