const paymentRouteMethod = "erpnext.accounts.invoice_payment_route.get_payment_route";

for (const doctype of ["Purchase Invoice", "Payment Request"]) {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			render_invoice_payment_route(frm);
			if (doctype === "Purchase Invoice") install_invoice_payment_confirmation(frm);
		},
		after_workflow_action(frm) {
			render_invoice_payment_route(frm);
		},
	});
}

async function render_invoice_payment_route(frm) {
	const field = frm.get_field("custom_payment_route_html");
	if (!field) return;
	const section = frm.fields_dict.custom_payment_route_section;
	if (section?.wrapper?.length) section.wrapper.parent().prepend(section.wrapper);
	if (frm.is_new()) {
		field.$wrapper.empty();
		frm.toggle_display("custom_payment_route_section", false);
		return;
	}
	const name = frm.doc.name;
	const response = await frappe.call({ method: paymentRouteMethod, args: { doctype: frm.doctype, name } });
	if (frm.doc.name !== name) return;
	const route = response.message;
	frm.toggle_display("custom_payment_route_section", Boolean(route?.visible));
	if (!route?.visible) {
		field.$wrapper.empty();
		return;
	}
	const state = frm.doc.workflow_state || (frm.doc.docstatus === 1 ? "Проведено" : "Чернетка");
	const rejected = state === "Відхилено";
	const stateClass = rejected ? "is-rejected" : state === "Потребує доопрацювання" ? "is-rework" : "";
	const currentIndex = rejected ? -1 : route.steps.findIndex((step) => !step.completed);
	const styles = {
		initiator: { role: "Initiator", icon: "edit" },
		department: { role: "Department Head", icon: "review" },
		ceo: { role: "Final Approver", icon: "check" },
		invoice: { role: "Buyer", icon: "clipboard" },
		treasury: { role: "Treasurer", icon: "es-line-payments" },
		payment: { role: "Treasurer", icon: "es-line-payments" },
	};
	const stages = route.steps
		.map((step, index) => {
			const stage = styles[step.key];
			const current = index === currentIndex;
			const status = step.completed ? "is-complete" : current ? "is-current" : "is-pending";
			const actorText =
				(step.users || []).map((user) => user.full_name || user.user).join(", ") ||
				(current
					? __("In progress")
					: step.completed
					? __("User is not recorded")
					: __("Not completed yet"));
			let role = __(stage.role);
			if (step.key === "ceo") {
				if (step.automatic && step.completed) role = __("Approved automatically");
				else if (route.ceo_administrator) role = __("Approved by Administrator");
				else if (current || step.completed) role += ` · ${route.ceo_votes}/${route.ceo_required}`;
			}
			const actor = step.automatic && step.completed ? "" : frappe.utils.escape_html(actorText);
			return `<div class="payment-route-segment"><div class="payment-route-step ${status}">
			<div class="payment-route-icon">${frappe.utils.icon(stage.icon, "sm")}</div>
			<div class="payment-route-copy"><div class="payment-route-title">${frappe.utils.escape_html(
				__(step.title)
			)}</div>
			<div class="payment-route-role">${frappe.utils.escape_html(role)}</div>
			<div class="payment-route-actor" title="${frappe.utils.escape_html(actorText)}">${actor}</div></div>
		</div></div>`;
		})
		.join("");
	const origin = route.source
		? `<div class="payment-route-origin">${__(route.source_doctype || "Consolidated Purchase Order")}:
		${erpnext.entity.html({
			name: route.source,
			icon: "file-text-o",
			route: ["Form", route.source_doctype || "Consolidated Purchase Order", route.source],
		})}
		· ${__("Created by")}: ${
				route.source_creator ? erpnext.entity.user(route.source_creator, { size: 18 }) : ""
		  }</div>`
		: "";
	const color = ["Проведено", "Погоджено"].includes(state)
		? "green"
		: rejected
		? "red"
		: state === "Потребує доопрацювання"
		? "orange"
		: ["Перевірка підрозділу", "Фінальне погодження"].includes(state)
		? "yellow"
		: "blue";
	field.$wrapper.html(`<style>
		.payment-route-card{margin:8px 0 18px;padding:14px 16px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg)}
		.payment-route-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}
		.payment-route-heading{font-size:var(--text-md);font-weight:600;color:var(--heading-color)}
		.payment-route-state{max-width:50%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
		.payment-route-origin{margin-bottom:14px;font-size:var(--text-sm);color:var(--text-muted)}
		.payment-route-origin a{font-weight:500}
		.payment-route-scroll{overflow:visible;padding:2px 0 4px}
		.payment-route{display:grid;grid-template-columns:repeat(${
			route.steps.length
		},minmax(0,1fr));align-items:start;gap:14px;width:100%;min-width:0}
		.payment-route-segment{min-width:0}
		.payment-route-step{display:flex;align-items:flex-start;gap:9px;width:100%;min-width:0}
		.payment-route-icon{display:flex;align-items:center;justify-content:center;width:34px;height:34px;flex:0 0 34px;border:1px solid var(--border-color);border-radius:50%;color:var(--text-muted);background:var(--control-bg)}
		.payment-route-copy{min-width:0;max-width:none}
		.payment-route-title{font-size:var(--text-sm);font-weight:600;line-height:1.25;color:var(--text-color);white-space:normal}
		.payment-route-role{margin-top:2px;font-size:var(--text-xs);line-height:1.25;color:var(--text-muted);white-space:normal;overflow-wrap:anywhere}
		.payment-route-actor{margin-top:4px;overflow:hidden;text-overflow:ellipsis;font-size:var(--text-xs);line-height:1.2;color:var(--text-color);white-space:nowrap}
		.payment-route-actor a{font-weight:500}
		.payment-route-step.is-complete .payment-route-icon{border-color:var(--green-500);background:var(--green-100);color:var(--green-700)}
		.payment-route-step.is-current .payment-route-icon{border-color:var(--blue-500);background:var(--blue-100);color:var(--blue-700);box-shadow:0 0 0 3px var(--blue-50)}
		.payment-route-step.is-pending{opacity:.5}
		.payment-route-card.is-rework .payment-route-step.is-current .payment-route-icon{border-color:var(--orange-500);background:var(--orange-100);color:var(--orange-700);box-shadow:0 0 0 3px var(--orange-50)}
		.payment-route-card.is-rejected .payment-route-icon{border-color:var(--red-300);color:var(--red-500)}
		@media(max-width:767px){.payment-route-card{padding:12px}.payment-route{grid-template-columns:1fr;gap:14px}}
	</style><div class="payment-route-card ${stateClass}"><div class="payment-route-head">
		<div class="payment-route-heading">${__("Approval Route")}</div>
		<span class="indicator-pill no-indicator-dot ${color} payment-route-state">${frappe.utils.escape_html(
		state
	)}</span>
	</div>${origin}<div class="payment-route-scroll"><div class="payment-route">${stages}</div></div></div>`);
}

function install_invoice_payment_confirmation(frm) {
	if (frm.__invoice_payment_confirmation || !frm.cscript.make_payment_entry) return;
	const original = frm.cscript.make_payment_entry.bind(frm.cscript);
	frm.cscript.make_payment_entry = async (...args) => {
		const response = await frappe.call({
			method: "erpnext.accounts.invoice_payment_route.get_invoice_payment_context",
			args: { invoice_name: frm.doc.name },
		});
		const context = response.message;
		if (!context.requests.length) return original(...args);
		if (!context.can_confirm) {
			frappe.msgprint(
				__(
					"The payment request has not completed approval. Complete its approval before paying this invoice."
				)
			);
			return;
		}
		const requests = context.requests.map((row) => frappe.utils.escape_html(row.name)).join(", ");
		const confirmed = await new Promise((resolve) =>
			frappe.confirm(
				__(
					"Payment requests already exist for this invoice: {0}. Confirm the treasury review and submit them before creating the payment?",
					[requests]
				),
				() => resolve(true),
				() => resolve(false)
			)
		);
		if (!confirmed) return;
		await frappe.call({
			method: "erpnext.accounts.invoice_payment_route.confirm_invoice_payment_requests",
			args: { invoice_name: frm.doc.name, request_names: context.requests.map((row) => row.name) },
		});
		return original(...args);
	};
	frm.__invoice_payment_confirmation = true;
}
