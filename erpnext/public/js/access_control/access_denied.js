frappe.provide("erpnext.access_control");

erpnext.access_control.denial = { pending: null, timer: null, dialog: null };

erpnext.access_control.USER_BLOCKERS = {
	no_role: () => __("None of the user's roles gives this access"),
	not_owner: () => __("The user's role gives this access only to their own documents"),
	user_permission: () =>
		__("The document is outside the values the user is allowed to work with (User Permission)"),
};

erpnext.access_control.blocker_text = (code, about_user) =>
	(about_user && erpnext.access_control.USER_BLOCKERS[code]
		? erpnext.access_control.USER_BLOCKERS[code]()
		: null) ||
	{
		no_role: __("None of your roles gives this access"),
		not_owner: __("Your role gives this access only to documents you created"),
		user_permission: __(
			"The document is outside the values you are allowed to work with (User Permission)"
		),
		controller: __("Access is limited by a rule of this document type"),
		not_submittable: __("This document type cannot be submitted"),
		not_importable: __("Import is not allowed for this document type"),
		unknown: __("The reason could not be determined"),
	}[code] ||
	code;

erpnext.access_control.hint_text = (code) =>
	({
		submitted_is_read_only: __("A submitted document cannot be edited, cancel and amend it instead"),
		cancel_before_delete: __("Cancel the document before deleting it"),
		cancelled_is_read_only: __("A cancelled document cannot be changed"),
		only_submitted_can_be_cancelled: __("Only a submitted document can be cancelled"),
		only_draft_can_be_submitted: __("Only a draft can be submitted"),
	}[code] || code);

erpnext.access_control.action_label = (context) => {
	if (context.kind === "page") return __("Open page");
	if (context.kind === "report") return __("Open report");
	if (context.kind !== "doctype") return __("Action");
	const right = context.ptype || "read";
	return erpnext.access_control.RIGHT_LABELS[right] || __(frappe.unscrub(right));
};

erpnext.access_control.server_message = (r) => {
	if (r._error_message) return r._error_message;
	try {
		return JSON.parse(r._server_messages || "[]")
			.map((raw) => {
				try {
					return JSON.parse(raw).message || raw;
				} catch (e) {
					return raw;
				}
			})
			.join("<br>");
	} catch (e) {
		return "";
	}
};

erpnext.access_control.route_context = (route) => {
	const [view, target, name] = route;
	if (view === "Form" && target) return { kind: "doctype", doctype: target, name, ptype: "read" };
	if (["List", "Report", "Tree", "Kanban", "Calendar", "Gantt", "Dashboard"].includes(view) && target)
		return { kind: "doctype", doctype: target, name: null, ptype: "read" };
	if (view === "query-report" && target) return { kind: "report", report: target };
	return view ? { kind: "page_or_doctype", slug: view } : { kind: "other" };
};

erpnext.access_control.with_route_name = (context) => {
	const [view, doctype, name] = frappe.get_route();
	return context.kind === "doctype" &&
		!context.name &&
		view === "Form" &&
		doctype === context.doctype &&
		name
		? { ...context, name }
		: context;
};

erpnext.access_control.capture = (r) => {
	const state = erpnext.access_control.denial;
	if (state.dialog && state.dialog.display) return;
	state.pending = {
		context: erpnext.access_control.with_route_name(r._access_denied || { kind: "other" }),
		message: erpnext.access_control.server_message(r),
		re_route: false,
	};
	clearTimeout(state.timer);
	state.timer = setTimeout(erpnext.access_control.flush, 50);
};

erpnext.access_control.flush = () => {
	const state = erpnext.access_control.denial;
	const pending = state.pending;
	state.pending = null;
	if (pending) erpnext.access_control.show_denial(pending);
};

erpnext.access_control.go_back = () => {
	frappe.route_flags.replace_route = true;
	const prev_route = frappe.get_prev_route();
	frappe.set_route(prev_route.length ? prev_route : "");
};

erpnext.access_control.roles_html = (roles) =>
	roles.length
		? roles
				.map(
					(role) =>
						`<span class="indicator-pill gray ac-right">${frappe.utils.escape_html(
							__(role)
						)}</span>`
				)
				.join(" ")
		: `<span class="text-muted">—</span>`;

erpnext.access_control.granting_html = (granting) => {
	const entries = Object.entries(granting || {});
	return entries.length
		? entries
				.map(
					([role, scope]) =>
						`<span class="indicator-pill blue ac-right">${frappe.utils.escape_html(__(role))}${
							scope === "owner" ? ` · ${__("own only")}` : ""
						}</span>`
				)
				.join(" ")
		: `<span class="text-muted">${__("No role gives this access")}</span>`;
};

erpnext.access_control.denial_html = (info, message) => {
	const esc = frappe.utils.escape_html;
	const blockers = (info.blockers || []).map(erpnext.access_control.blocker_text);
	const hints = (info.hints || []).map(erpnext.access_control.hint_text);
	const pending = info.pending
		? `<div class="alert alert-info">${__("Your request {0} is waiting for a decision since {1}", [
				`<a href="/app/access-request/${encodeURIComponent(info.pending.name)}">${esc(
					info.pending.name
				)}</a>`,
				frappe.datetime.str_to_user(info.pending.creation),
		  ])}</div>`
		: "";
	const allowed = info.allowed
		? `<div class="alert alert-success">${__(
				"You have this access now. Reload the page to continue"
		  )}</div>`
		: "";
	const no_managers =
		!info.has_managers && !info.pending && !info.allowed
			? `<div class="alert alert-warning">${__(
					"No Access Manager is assigned yet. Your request will be seen by a System Manager"
			  )}</div>`
			: "";
	return `<div class="ac-denial">
		${
			info.title
				? `<p><span class="text-muted">${esc(
						erpnext.access_control.action_label(info.context)
				  )}:</span> <b>${esc(info.title)}</b></p>`
				: ""
		}
		${allowed}
		${
			blockers.length && !info.allowed
				? `<div class="alert alert-warning"><ul class="ac-list">${blockers
						.map((text) => `<li>${esc(text)}</li>`)
						.join("")}</ul></div>`
				: ""
		}
		${
			hints.length
				? `<ul class="ac-list text-muted">${hints
						.map((text) => `<li>${esc(text)}</li>`)
						.join("")}</ul>`
				: ""
		}
		${message && info.context.kind === "other" ? `<div class="text-muted small ac-message">${message}</div>` : ""}
		${pending}
		${no_managers}
	</div>`;
};

erpnext.access_control.show_denial = ({ context, message, re_route }) =>
	frappe
		.xcall("erpnext.access_control.denial.get_denial", { context })
		.then((info) => erpnext.access_control.denial_dialog(info, message, re_route));

erpnext.access_control.denial_dialog = (info, message, re_route) => {
	const can_ask = info.can_request && !info.pending && !info.allowed;
	const dialog = new frappe.ui.Dialog({
		title: __("Not permitted"),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "info" },
			{
				fieldtype: "MultiCheck",
				fieldname: "rights",
				label: __("Which rights do you need?"),
				columns: 4,
				sort_options: false,
				hidden: !can_ask || !(info.rights || []).length,
				description: __("{0} and {1} are always included", [
					erpnext.access_control.RIGHT_LABELS.read,
					erpnext.access_control.action_label(info.context),
				]),
				options: (info.rights || []).map((right) => ({
					label: erpnext.access_control.RIGHT_LABELS[right] || __(frappe.unscrub(right)),
					value: right,
					checked: right === "read" || right === (info.context.ptype || "read"),
				})),
			},
			{
				fieldtype: "Small Text",
				fieldname: "reason",
				label: __("Why do you need this access?"),
				hidden: !can_ask,
			},
		],
		onhide: () => {
			erpnext.access_control.denial.dialog = null;
			if (re_route && !info.allowed) erpnext.access_control.go_back();
		},
	});
	dialog.fields_dict.info.$wrapper.html(
		erpnext.access_control.STYLE + erpnext.access_control.denial_html(info, message)
	);
	if (info.allowed) {
		dialog.set_primary_action(__("Reload"), () => window.location.reload());
	} else if (can_ask) {
		dialog.set_primary_action(__("Request access"), ({ reason, rights }) => {
			if (!(reason || "").trim()) {
				frappe.msgprint(__("Please describe why you need access"));
				return;
			}
			frappe
				.xcall("erpnext.access_control.denial.create_request", {
					context: info.context,
					reason,
					route: frappe.get_route_str(),
					message,
					rights: rights || [],
				})
				.then(({ name }) => {
					dialog.hide();
					frappe.show_alert({
						message: __("Access request {0} sent", [name]),
						indicator: "green",
					});
				});
		});
	} else if (info.pending) {
		dialog.set_primary_action(__("Cancel request"), () =>
			frappe
				.xcall("erpnext.access_control.doctype.access_request.access_request.cancel_request", {
					name: info.pending.name,
				})
				.then(() => {
					dialog.hide();
					frappe.show_alert({ message: __("Request cancelled"), indicator: "orange" });
				})
		);
	}
	erpnext.access_control.denial.dialog = dialog;
	dialog.show();
	return dialog;
};

erpnext.access_control.install_denial_handlers = () => {
	frappe.request.on_error("PermissionError", erpnext.access_control.capture);

	const msgprint = frappe.msgprint;
	frappe.msgprint = function (msg, title) {
		const data = $.isPlainObject(msg) ? msg : { title };
		const state = erpnext.access_control.denial;
		const ours = state.pending || (state.dialog && state.dialog.display);
		if (ours && data.title === __("Not permitted")) {
			if (state.pending && data.re_route) state.pending.re_route = true;
			return;
		}
		return msgprint.apply(this, arguments);
	};

	const show_not_permitted = frappe.show_not_permitted;
	frappe.show_not_permitted = function (page_name) {
		show_not_permitted.apply(this, arguments);
		const context = erpnext.access_control.route_context(frappe.get_route());
		const page = frappe.pages[page_name || frappe.get_route_str()];
		$(`<button class="btn btn-primary btn-sm ac-why mr-2">${__("Why? Request access")}</button>`)
			.on("click", () => erpnext.access_control.show_denial({ context, message: "", re_route: false }))
			.insertBefore($(page).find(".message-page-content .btn-home"));
	};
};

erpnext.access_control.listen_decisions = () =>
	frappe.realtime.on("access_request_decided", (data) => {
		if (data.status === "Approved") {
			frappe.msgprint({
				title: __("Access granted"),
				indicator: "green",
				message: __("Your request {0} was approved. Reload the page to use the new access", [
					frappe.utils.escape_html(data.title),
				]),
				primary_action: { label: __("Reload"), action: () => window.location.reload() },
			});
			return;
		}
		const title = frappe.utils.escape_html(data.title);
		frappe.show_alert(
			{
				message:
					data.status === "Revoked"
						? __("Access from your request {0} was revoked", [title])
						: __("Your access request {0} was rejected", [title]),
				indicator: data.status === "Revoked" ? "orange" : "red",
			},
			10
		);
	});

erpnext.access_control.install_denial_handlers();

$(document).on("app_ready", () => erpnext.access_control.listen_decisions());
