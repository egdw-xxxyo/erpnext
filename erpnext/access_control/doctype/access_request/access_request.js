const AR_METHOD = "erpnext.access_control.doctype.access_request.access_request";

frappe.ui.form.on("Access Request", {
	refresh(frm) {
		if (frm.doc.status !== "Pending") return;
		const own = frm.doc.user === frappe.session.user;
		const manager = erpnext.access_control.can_manage();
		frm.set_intro(
			own
				? __("Your request is waiting for a decision of the Access Manager")
				: __("Check what the user will get before approving"),
			"blue"
		);
		if (manager && !own) {
			frm.add_custom_button(__("Approve"), () => erpnext.access_control.approve_dialog(frm)).addClass(
				"btn-primary"
			);
			frm.add_custom_button(__("Reject"), () => erpnext.access_control.reject_dialog(frm));
		}
		if (own) {
			frm.add_custom_button(__("Cancel request"), () =>
				frappe
					.xcall(`${AR_METHOD}.cancel_request`, { name: frm.doc.name })
					.then(() => frm.reload_doc())
			);
		}
	},
});

frappe.provide("erpnext.access_control");

erpnext.access_control.situation_html = (frm, options) => {
	const esc = frappe.utils.escape_html;
	const situation = options.situation || {};
	const blockers = situation.allowed
		? `<div class="alert alert-success">${__("The user has this access now")}</div>`
		: (situation.blockers || []).length
		? `<div class="alert alert-warning"><ul class="ac-list">${situation.blockers
				.map((code) => `<li>${esc(erpnext.access_control.blocker_text(code, true))}</li>`)
				.join("")}</ul></div>`
		: "";
	const hints = (situation.hints || [])
		.map((code) => `<li>${esc(erpnext.access_control.hint_text(code))}</li>`)
		.join("");
	const workflow = situation.workflow
		? `<p><span class="text-muted">${__("Workflow state")}:</span> ${esc(
				situation.workflow.state_label || "—"
		  )} · <span class="text-muted">${__(
				"Can edit in this state"
		  )}:</span> ${erpnext.access_control.roles_html(situation.workflow.edit_roles || [])}</p>`
		: "";
	const never = options.never_granted.length
		? `<p class="text-muted">${__(
				"Also given by roles that are never granted through a request"
		  )}: ${options.never_granted.map((role) => esc(__(role))).join(", ")}</p>`
		: "";
	const disabled = options.user_enabled
		? ""
		: `<div class="alert alert-danger">${__("The user is disabled")}</div>`;
	return `<div class="ac-denial">
		${disabled}
		<p>${erpnext.entity.user(options.user, { size: 24 })}</p>
		<p><span class="text-muted">${__("Requested access")}:</span> <b>${esc(frm.doc.title || "")}</b></p>
		<p><span class="text-muted">${__("Reason")}:</span> ${esc(frm.doc.reason || "")}</p>
		${blockers}
		${hints ? `<ul class="ac-list text-muted">${hints}</ul>` : ""}
		${workflow}
		<p><span class="text-muted">${__("User roles")}:</span> ${erpnext.access_control.roles_html(
		options.user_roles
	)}</p>
		<p><span class="text-muted">${__("Access is given by roles")}:</span> ${erpnext.access_control.granting_html(
		(situation.granting_roles && Object.keys(situation.granting_roles).length
			? situation.granting_roles
			: null) || {}
	)}</p>
		${never}
	</div>`;
};

erpnext.access_control.resolution_options = (options) =>
	[
		{ value: "Role", label: __("Role") },
		options.share_rights ? { value: "Share", label: __("Share this document") } : null,
		options.user_permissions.length ? { value: "User Permission", label: __("User Permission") } : null,
	].filter(Boolean);

erpnext.access_control.candidate_label = (candidate) =>
	[
		__(candidate.role),
		__("+{0} new rights", [candidate.size]),
		candidate.scope === "owner" ? __("own only") : null,
		__("holders: {0}", [candidate.users]),
	]
		.filter(Boolean)
		.join(" · ");

erpnext.access_control.profile_options = (profiles) =>
	profiles.length
		? [
				...profiles.map((profile) => ({
					value: `profile:${profile.name}`,
					label: __("Add the role to profile {0} (users: {1})", [profile.name, profile.users]),
				})),
				{ value: "unlink", label: __("Unlink role profiles, keep the roles directly") },
		  ]
		: [];

erpnext.access_control.chosen_role = (dialog) => dialog.get_value("other_role") || dialog.get_value("role");

erpnext.access_control.has_sensitive = (delta) =>
	Boolean(delta && (delta.doctypes || []).some((entry) => entry.sensitive || entry.risky_rights.length));

erpnext.access_control.refresh_impact = (dialog, options) => {
	const wrapper = dialog.fields_dict.impact.$wrapper;
	const resolution = dialog.get_value("resolution");
	dialog.current_delta = null;
	if (resolution === "Share") {
		wrapper.html(
			`<p>${__(
				"The user gets these rights on this document only"
			)}: ${erpnext.access_control.roles_html(
				(dialog.get_value("share_rights") || []).map(
					(right) => erpnext.access_control.RIGHT_LABELS[right] || right
				)
			)}</p>`
		);
		return;
	}
	if (resolution === "User Permission") {
		wrapper.html(
			`<p>${__(
				"The user can work with documents of this value as well, in every document type that uses it"
			)}</p>`
		);
		return;
	}
	const role = erpnext.access_control.chosen_role(dialog);
	if (!role) {
		wrapper.html(`<p class="text-muted">${__("Choose a role")}</p>`);
		return;
	}
	wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
	frappe
		.xcall("erpnext.access_control.permissions_engine.get_role_delta", {
			user: options.user,
			role,
		})
		.then((delta) => {
			if (erpnext.access_control.chosen_role(dialog) !== role) return;
			if (delta.already_has) {
				wrapper.html(`<div class="alert alert-info">${__("The user already has this role")}</div>`);
				return;
			}
			dialog.current_delta = delta;
			const profile = dialog.get_value("profile_action") || "";
			const profile_note = profile.startsWith("profile:")
				? `<div class="alert alert-warning">${__(
						"The role is added to role profile {0}, so every user with this profile gets it too",
						[frappe.utils.escape_html(profile.slice("profile:".length))]
				  )}</div>`
				: "";
			wrapper.html(
				erpnext.access_control.STYLE + profile_note + erpnext.access_control.render_grants(delta)
			);
		});
};

erpnext.access_control.approve_dialog = (frm) =>
	frappe.xcall(`${AR_METHOD}.get_approval_options`, { name: frm.doc.name }).then((options) => {
		const resolutions = erpnext.access_control.resolution_options(options);
		const profiles = erpnext.access_control.profile_options(options.role_profiles);
		let dialog = null;
		const refresh = () => dialog && erpnext.access_control.refresh_impact(dialog, options);
		dialog = new frappe.ui.Dialog({
			title: __("Approve request {0}", [frm.doc.name]),
			size: "extra-large",
			fields: [
				{ fieldtype: "HTML", fieldname: "situation" },
				{ fieldtype: "Section Break" },
				{
					fieldtype: "Select",
					fieldname: "resolution",
					label: __("Grant by"),
					options: resolutions,
					default: resolutions[0].value,
					reqd: 1,
					onchange: refresh,
				},
				{
					fieldtype: "Select",
					fieldname: "role",
					label: __("Role"),
					options: options.candidates.map((candidate) => ({
						value: candidate.role,
						label: erpnext.access_control.candidate_label(candidate),
					})),
					default: options.candidates.length ? options.candidates[0].role : undefined,
					description: __("Sorted from the smallest extra access"),
					depends_on: "eval:doc.resolution==='Role'",
					onchange: refresh,
				},
				{
					fieldtype: "Link",
					fieldname: "other_role",
					label: __("Or another role"),
					options: "Role",
					depends_on: "eval:doc.resolution==='Role'",
					onchange: refresh,
				},
				{
					fieldtype: "Select",
					fieldname: "profile_action",
					label: __("Role profile"),
					options: profiles,
					default: profiles.length ? profiles[profiles.length - 1].value : undefined,
					hidden: !profiles.length,
					description: __(
						"While the user has a role profile, a role added directly is removed on the next save"
					),
					depends_on: "eval:doc.resolution==='Role'",
					onchange: refresh,
				},
				{
					fieldtype: "MultiCheck",
					fieldname: "share_rights",
					label: __("Rights"),
					options: (options.share_rights ? ["read", "write", "submit", "share"] : []).map(
						(right) => ({
							label: erpnext.access_control.RIGHT_LABELS[right],
							value: right,
							checked: (options.share_rights || []).includes(right),
						})
					),
					depends_on: "eval:doc.resolution==='Share'",
					onchange: refresh,
				},
				{
					fieldtype: "Select",
					fieldname: "user_permission",
					label: __("Allow value"),
					options: options.user_permissions.map((candidate) => ({
						value: JSON.stringify(candidate),
						label: `${__(candidate.allow)}: ${candidate.for_value}`,
					})),
					depends_on: "eval:doc.resolution==='User Permission'",
					onchange: refresh,
				},
				{ fieldtype: "Section Break", label: __("What the user will get") },
				{ fieldtype: "HTML", fieldname: "impact" },
				{ fieldtype: "Section Break" },
				{ fieldtype: "Data", fieldname: "note", label: __("Note for the user") },
			],
			primary_action_label: __("Approve"),
			primary_action(values) {
				const submit = () =>
					frappe
						.xcall(`${AR_METHOD}.approve`, {
							name: frm.doc.name,
							resolution: values.resolution,
							role: erpnext.access_control.chosen_role(dialog),
							profile_action: values.profile_action,
							share_rights: values.share_rights,
							...(values.user_permission ? JSON.parse(values.user_permission) : {}),
							note: values.note,
						})
						.then(() => {
							dialog.hide();
							frappe.show_alert({ message: __("Access granted"), indicator: "green" });
							frm.reload_doc();
						});
				if (
					values.resolution === "Role" &&
					erpnext.access_control.has_sensitive(dialog.current_delta)
				) {
					frappe.confirm(
						__(
							"This role gives sensitive data or risky rights (delete, cancel, export, import, share). Approve anyway?"
						),
						submit
					);
					return;
				}
				submit();
			},
		});
		dialog.fields_dict.situation.$wrapper.html(
			erpnext.access_control.STYLE + erpnext.access_control.situation_html(frm, options)
		);
		dialog.show();
		refresh();
	});

erpnext.access_control.reject_dialog = (frm) => {
	const dialog = new frappe.ui.Dialog({
		title: __("Reject request {0}", [frm.doc.name]),
		fields: [{ fieldtype: "Small Text", fieldname: "note", label: __("Note for the user") }],
		primary_action_label: __("Reject"),
		primary_action: ({ note }) =>
			frappe.xcall(`${AR_METHOD}.reject`, { name: frm.doc.name, note }).then(() => {
				dialog.hide();
				frm.reload_doc();
			}),
	});
	dialog.show();
};
