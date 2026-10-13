const AR_METHOD = "erpnext.access_control.doctype.access_request.access_request";

frappe.ui.form.on("Access Request", {
	refresh(frm) {
		if (frm.doc.__onload?.revocable && erpnext.access_control.can_manage()) {
			frm.add_custom_button(__("Revoke"), () => erpnext.access_control.revoke_dialog(frm));
		}
		if (frm.doc.status === "Approved" && frm.doc.grant_log && !frm.doc.__onload?.revocable) {
			frm.set_intro(
				__("Access was given through a role profile change, it cannot be revoked from the request"),
				"blue"
			);
		}
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
	const link = erpnext.access_control.request_link(frm.doc);
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
		<p><span class="text-muted">${__("Requested access")}:</span> ${
		link
			? `<a href="${link}" target="_blank"><b>${esc(frm.doc.title || "")}</b></a>`
			: `<b>${esc(frm.doc.title || "")}</b>`
	}</p>
		${frm.doc.reason ? `<p><span class="text-muted">${__("Reason")}:</span> ${esc(frm.doc.reason)}</p>` : ""}
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
		"Role",
		options.right_roles.length ? "Role Right" : null,
		options.profile_candidates.length ? "Role Profile" : null,
		options.share_rights ? "Document Share" : null,
		options.user_permissions.length ? "User Permission" : null,
	]
		.filter(Boolean)
		.map((value) => ({ value, label: erpnext.access_control.RESOLUTION_LABELS[value]() }));

erpnext.access_control.UNAVAILABLE_REASONS = {
	no_document: () => __("The request is not for a specific document"),
	not_shareable: () => __("This right cannot be given by sharing a document"),
	no_restrictions: () =>
		__("The user has no User Permission restrictions here, adding one would narrow access instead"),
	already_allowed: () => __("The document's values are already allowed for the user"),
	not_doctype: () => __("Rights of a role can be added only for a document type"),
	no_right_roles: () =>
		__("The user has no role whose rights you may change (your own roles need a System Manager)"),
	protected_doctype: () =>
		__("Rights of system document types (users, roles, permissions, scripts) are not changed here"),
	no_profile_grants: () =>
		__(
			"No role profile gives this access (profiles with System Manager or Access Manager are not offered)"
		),
};

erpnext.access_control.RESOLUTION_LABELS = {
	Role: () => __("Give a role"),
	"Role Right": () => __("Add rights to a user's role"),
	"Role Profile": () => __("Give a role profile"),
	"Document Share": () => __("Open access to this document only"),
	"User Permission": () => __("Allow the value (user permission)"),
};

erpnext.access_control.unavailable_html = (unavailable) => {
	const entries = Object.entries(unavailable || {});
	return entries.length
		? `<div class="ac-denial text-muted small"><div>${__(
				"Not available"
		  )}:</div><ul class="ac-list">${entries
				.map(
					([resolution, code]) =>
						`<li><b>${erpnext.access_control.RESOLUTION_LABELS[resolution]()}</b> — ${(
							erpnext.access_control.UNAVAILABLE_REASONS[code] || (() => code)
						)()}</li>`
				)
				.join("")}</ul></div>`
		: "";
};

erpnext.access_control.right_label = (right) =>
	erpnext.access_control.RIGHT_LABELS[right] || __(frappe.unscrub(right));

erpnext.access_control.missing_for = (candidate, wanted) =>
	wanted.filter((right) => !(candidate.coverage || {})[right]);

erpnext.access_control.coverage_note = (missing, wanted) => {
	if (!wanted.length) return null;
	return missing.length
		? __("lacks: {0}", [missing.map(erpnext.access_control.right_label).join(", ")])
		: __("covers all chosen");
};

erpnext.access_control.by_coverage = (candidates, wanted) =>
	candidates
		.map((candidate, index) => ({
			candidate,
			index,
			missing: erpnext.access_control.missing_for(candidate, wanted),
		}))
		.sort((a, b) => a.missing.length - b.missing.length || a.index - b.index);

erpnext.access_control.PICK_LISTS = {
	role_list: {
		label: () => __("Roles"),
		help: () => __("Sorted by the chosen rights first, then from the smallest extra access"),
	},
	profile_list: {
		label: () => __("Role Profiles"),
		help: () => __("Profiles that give this access, sorted from the smallest change"),
	},
};

erpnext.access_control.picked = (dialog, fieldname) => dialog.fields_dict[fieldname].get_value() || [];

erpnext.access_control.describe_pick = (control) => {
	const help = erpnext.access_control.PICK_LISTS[control.df.fieldname].help();
	const chosen = control._options
		.filter((option) => control.values.includes(option.value))
		.map((option) => option.label);
	control.df.description = chosen.length
		? `<span class="text-body">${__("Chosen: {0}", [chosen.join(", ")])}</span><br>${help}`
		: help;
	control.set_description(control.df.description);
};

erpnext.access_control.watch_pick_list = (dialog, fieldname, on_change) => {
	const control = dialog.fields_dict[fieldname];
	control.$list_wrapper.find(".select-all-options").remove();
	const update_status = control.update_status.bind(control);
	control.update_status = () => {
		update_status();
		erpnext.access_control.describe_pick(control);
		on_change();
	};
};

erpnext.access_control.set_pick_list = (dialog, fieldname, items, selected) => {
	const control = dialog.fields_dict[fieldname];
	const values = selected.filter((value) => items.some((item) => item.value === value));
	control.df.options = items;
	control._options = items;
	control.values = values;
	control._selected_values = items.filter((item) => values.includes(item.value));
	control.update_status();
	erpnext.access_control.describe_pick(control);
};

erpnext.access_control.pick_list_field = (fieldname, resolution) => ({
	fieldtype: "MultiSelectList",
	fieldname,
	label: erpnext.access_control.PICK_LISTS[fieldname].label(),
	description: erpnext.access_control.PICK_LISTS[fieldname].help(),
	depends_on: `eval:doc.resolution==='${resolution}'`,
});

erpnext.access_control.CHECK_LISTS = {
	value_list: {
		title: () => __("Allow values"),
		description: () => __("Values of this document the user is not allowed to work with yet"),
	},
};

erpnext.access_control.check_list_html = (fieldname, items, selected) => {
	const esc = frappe.utils.escape_html;
	const spec = erpnext.access_control.CHECK_LISTS[fieldname];
	const rows = items.length
		? items
				.map(
					({ value, label }) => `<div class="checkbox"><label>
						<input type="checkbox" value="${esc(value)}" ${selected.includes(value) ? "checked" : ""}>
						<span class="label-area">${esc(label)}</span>
					</label></div>`
				)
				.join("")
		: `<p class="text-muted">—</p>`;
	return `<div class="form-group">
		<label class="control-label">${spec.title()}</label>
		${rows}
		<p class="help-box small text-muted">${spec.description()}</p>
	</div>`;
};

erpnext.access_control.checked_values = (dialog, fieldname) =>
	dialog.fields_dict[fieldname].$wrapper
		.find("input:checked")
		.map((_, input) => input.value)
		.get();

erpnext.access_control.render_check_list = (dialog, fieldname, items, selected) =>
	dialog.fields_dict[fieldname].$wrapper.html(
		erpnext.access_control.check_list_html(
			fieldname,
			items,
			selected.filter((value) => items.some((item) => item.value === value))
		)
	);

erpnext.access_control.role_select_options = (pool, wanted) =>
	erpnext.access_control.by_coverage(pool.candidates, wanted).map(({ candidate, missing }) => ({
		value: candidate.role,
		label: frappe.utils.escape_html(__(candidate.role)),
		description: frappe.utils.escape_html(
			erpnext.access_control.candidate_details(candidate, missing, wanted)
		),
	}));

erpnext.access_control.profile_select_options = (pool, wanted) =>
	erpnext.access_control.by_coverage(pool.profile_candidates, wanted).map(({ candidate, missing }) => ({
		value: candidate.profile,
		label: frappe.utils.escape_html(candidate.profile),
		description: frappe.utils.escape_html(
			erpnext.access_control.profile_candidate_details(candidate, missing, wanted)
		),
	}));

erpnext.access_control.share_coverage = (current, shared) => ({
	...current,
	...Object.fromEntries(shared.map((right) => [right, "all"])),
	...(shared.includes("read") ? { print: "all", email: "all" } : {}),
});

erpnext.access_control.wanted_rights = (dialog, options) =>
	options.rights.length ? dialog.get_value("rights") || [] : [];

erpnext.access_control.profile_mode = (dialog, options) =>
	options.role_profiles.length ? dialog.get_value("profile_mode") || "add" : "add";

erpnext.access_control.chosen_coverage = (dialog, options) => {
	const resolution = dialog.get_value("resolution");
	if (resolution === "Document Share")
		return erpnext.access_control.share_coverage(
			options.current_coverage,
			dialog.get_value("share_rights") || []
		);
	if (resolution === "User Permission") return options.current_coverage;
	return dialog.fetched_coverage;
};

erpnext.access_control.coverage_html = (wanted, covered) => {
	const esc = frappe.utils.escape_html;
	const missing = wanted.filter((right) => !covered[right]);
	const pills = wanted
		.map((right) => {
			const label = esc(erpnext.access_control.right_label(right));
			const scope = covered[right];
			return scope
				? `<span class="indicator-pill green ac-right"><i class="fa fa-check"></i> ${label}${
						scope === "owner" ? ` · ${__("own only")}` : ""
				  }</span>`
				: `<span class="indicator-pill red ac-right"><i class="fa fa-times"></i> ${label}</span>`;
		})
		.join(" ");
	const summary = missing.length
		? `<span class="text-danger">${__("Not covered: {0}", [
				missing.map((right) => esc(erpnext.access_control.right_label(right))).join(", "),
		  ])}</span>`
		: `<span class="text-success">${__("Covers all chosen rights")}</span>`;
	return `<div class="ac-denial"><p><span class="text-muted">${__(
		"Chosen rights"
	)}:</span> ${pills}</p><p>${summary}</p></div>`;
};

erpnext.access_control.render_coverage = (dialog, options) => {
	const wanted = erpnext.access_control.wanted_rights(dialog, options);
	const covered = erpnext.access_control.chosen_coverage(dialog, options);
	dialog.fields_dict.coverage.$wrapper.html(
		!wanted.length
			? ""
			: covered
			? erpnext.access_control.coverage_html(wanted, covered)
			: `<p class="text-muted">${__("Loading...")}</p>`
	);
};

erpnext.access_control.coverage_args = (dialog, options) => {
	const resolution = dialog.get_value("resolution");
	if (resolution === "Role") {
		const roles = erpnext.access_control.picked(dialog, "role_list");
		return roles.length ? { roles } : null;
	}
	if (resolution === "Role Profile") {
		const profiles = erpnext.access_control.picked(dialog, "profile_list");
		return profiles.length
			? { profiles, mode: erpnext.access_control.profile_mode(dialog, options) }
			: null;
	}
	return null;
};

erpnext.access_control.fetch_coverage = (dialog, options) => {
	dialog.fetched_coverage = null;
	const args = options.rights.length ? erpnext.access_control.coverage_args(dialog, options) : null;
	const key = JSON.stringify(args);
	dialog.coverage_key = key;
	erpnext.access_control.render_coverage(dialog, options);
	if (!args) return;
	frappe.xcall(`${AR_METHOD}.get_coverage`, { name: options.name, ...args }).then((covered) => {
		if (dialog.coverage_key !== key) return;
		dialog.fetched_coverage = covered;
		erpnext.access_control.render_coverage(dialog, options);
	});
};

erpnext.access_control.relabel_candidates = (dialog, options) => {
	const wanted = erpnext.access_control.wanted_rights(dialog, options);
	const pool = dialog.pool || options;
	erpnext.access_control.set_pick_list(
		dialog,
		"role_list",
		erpnext.access_control.role_select_options(pool, wanted),
		erpnext.access_control.picked(dialog, "role_list")
	);
	erpnext.access_control.set_pick_list(
		dialog,
		"profile_list",
		erpnext.access_control.profile_select_options(pool, wanted),
		erpnext.access_control.picked(dialog, "profile_list")
	);
};

erpnext.access_control.fetch_candidates = (dialog, options) => {
	const rights = erpnext.access_control.wanted_rights(dialog, options);
	const key = JSON.stringify(rights);
	dialog.pool_key = key;
	frappe.xcall(`${AR_METHOD}.get_candidates`, { name: options.name, rights }).then((pool) => {
		if (dialog.pool_key !== key) return;
		dialog.pool = pool;
		erpnext.access_control.relabel_candidates(dialog, options);
	});
};

erpnext.access_control.on_rights_change = (dialog, options) => {
	erpnext.access_control.relabel_candidates(dialog, options);
	erpnext.access_control.render_coverage(dialog, options);
	dialog.refetch_candidates();
	if (dialog.get_value("resolution") === "Role Right") dialog.refetch_role_right();
};

erpnext.access_control.approval_warnings = (dialog, options, values) => {
	const esc = frappe.utils.escape_html;
	const delta = dialog.current_delta;
	const wanted = erpnext.access_control.wanted_rights(dialog, options);
	const covered = erpnext.access_control.chosen_coverage(dialog, options) || {};
	const missing = wanted.filter((right) => !covered[right]);
	const lost = values.resolution === "Role Profile" && delta ? delta.lost_roles : [];
	const preview = values.resolution === "Role Right" ? dialog.role_right_preview : null;
	return [
		missing.length
			? __("The chosen grant does not give: {0}", [
					missing.map((right) => esc(erpnext.access_control.right_label(right))).join(", "),
			  ])
			: null,
		lost.length
			? __("The user will lose roles: {0}", [lost.map((role) => esc(__(role))).join(", ")])
			: null,
		preview && preview.add.length
			? __("Rights of role {0} change for every user with it, users: {1}", [
					esc(__(preview.role)),
					preview.users,
			  ])
			: null,
		values.resolution === "Role Profile" ||
		(values.resolution === "Role" && (values.profile_action || "").startsWith("profile:"))
			? __("A role profile change cannot be revoked from the request later")
			: null,
		["Role", "Role Profile"].includes(values.resolution) && erpnext.access_control.has_sensitive(delta)
			? __("This grant gives sensitive data or risky rights (delete, cancel, export, import, share)")
			: null,
	].filter(Boolean);
};

erpnext.access_control.candidate_details = (candidate, missing = [], wanted = []) =>
	[
		erpnext.access_control.coverage_note(missing, wanted),
		__("+{0} new rights", [candidate.size]),
		candidate.scope === "owner" ? __("own only") : null,
		__("holders: {0}", [candidate.users]),
	]
		.filter(Boolean)
		.join(" · ");

erpnext.access_control.profile_candidate_details = (candidate, missing = [], wanted = []) =>
	[
		erpnext.access_control.coverage_note(missing, wanted),
		__("+{0} new rights", [candidate.size]),
		candidate.lost_roles.length ? __("removes {0} roles", [candidate.lost_roles.length]) : null,
		__("users: {0}", [candidate.users]),
	]
		.filter(Boolean)
		.join(" · ");

erpnext.access_control.profile_mode_options = (profiles) => {
	const names = profiles.map((profile) => profile.name).join(", ");
	return [
		{ value: "add", label: __("Add to the current profiles ({0})", [names]) },
		{ value: "replace", label: __("Replace the current profiles ({0})", [names]) },
	];
};

erpnext.access_control.tabs_html = (tabs) =>
	`<div class="ac-tabs">
		<ul class="nav nav-tabs">${tabs
			.map(
				(tab, index) =>
					`<li class="nav-item"><a href="#" class="nav-link ${index ? "" : "active"} ${
						tab.danger ? "text-danger" : ""
					}" data-ac-tab="${index}">${tab.label}</a></li>`
			)
			.join("")}</ul>
		${tabs
			.map(
				(tab, index) =>
					`<div class="pt-3" data-ac-pane="${index}" ${index ? "hidden" : ""}>${tab.html}</div>`
			)
			.join("")}
	</div>`;

erpnext.access_control.bind_tabs = (wrapper) =>
	wrapper.off("click.ac-tabs").on("click.ac-tabs", ".ac-tabs [data-ac-tab]", (event) => {
		event.preventDefault();
		const $link = $(event.currentTarget);
		const $tabs = $link.closest(".ac-tabs");
		const index = String($link.data("ac-tab"));
		$tabs.find("[data-ac-tab]").removeClass("active");
		$link.addClass("active");
		$tabs.find("[data-ac-pane]").each((_, pane) => {
			pane.hidden = String($(pane).data("ac-pane")) !== index;
		});
	});

erpnext.access_control.profile_impact_html = (delta) => {
	const esc = frappe.utils.escape_html;
	const lost_roles = delta.lost_roles.map((role) => esc(__(role))).join(", ");
	const loses = delta.lost_roles.length || delta.lost.doctypes.length;
	const summary = delta.lost_roles.length
		? `<div class="alert alert-danger">
			<div>${__("The user will lose roles: {0}", [`<b>${lost_roles}</b>`])}</div>
			<div class="small">${__("A role profile replaces every role given directly, see the Loses tab")}</div>
		</div>`
		: "";
	const gains_html = `<p>${__("Roles the user gets")}: ${erpnext.access_control.roles_html(
		delta.gained_roles
	)}</p>${erpnext.access_control.render_grants(delta)}`;
	const losses_html = loses
		? `<p>${__("Roles the user loses")}: ${erpnext.access_control.roles_html(
				delta.lost_roles
		  )}</p>${erpnext.access_control.render_grants(delta.lost)}`
		: `<p class="text-muted">${__("The user loses nothing")}</p>`;
	return (
		summary +
		erpnext.access_control.tabs_html([
			{ label: `${__("Gets")} (${delta.doctypes.length})`, html: gains_html },
			{
				label: `${__("Loses")} (${delta.lost.doctypes.length})`,
				html: losses_html,
				danger: Boolean(loses),
			},
		])
	);
};

erpnext.access_control.profile_impact = (dialog, options, wrapper) => {
	const profiles = erpnext.access_control.picked(dialog, "profile_list");
	const mode = erpnext.access_control.profile_mode(dialog, options);
	if (!profiles.length) {
		wrapper.html(`<p class="text-muted">${__("Choose a role profile")}</p>`);
		return;
	}
	wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
	const key = JSON.stringify([profiles, mode]);
	dialog.profile_key = key;
	frappe.xcall(`${AR_METHOD}.get_profile_delta`, { name: options.name, profiles, mode }).then((delta) => {
		if (dialog.profile_key !== key) return;
		dialog.current_delta = delta;
		wrapper.html(erpnext.access_control.STYLE + erpnext.access_control.profile_impact_html(delta));
		erpnext.access_control.bind_tabs(wrapper);
	});
};

erpnext.access_control.profile_options = (profiles) =>
	profiles.length
		? [
				...profiles.map((profile) => ({
					value: `profile:${profile.name}`,
					label: __("Add the roles to profile {0} (users: {1})", [profile.name, profile.users]),
				})),
				{ value: "unlink", label: __("Unlink role profiles, keep the roles directly") },
		  ]
		: [];

erpnext.access_control.role_right_html = (preview, doctype) => {
	const esc = frappe.utils.escape_html;
	const role = `<b>${esc(__(preview.role))}</b>`;
	if (preview.refusal) return `<div class="alert alert-danger">${esc(preview.refusal_text)}</div>`;
	if (!preview.add.length)
		return `<div class="alert alert-info">${__("Role {0} already gives the chosen rights", [
			role,
		])}</div>`;
	const added = preview.add.map((right) => esc(erpnext.access_control.right_label(right))).join(", ");
	const profiles = preview.role_profiles.length
		? ` ${__("Profiles with this role: {0}", [preview.role_profiles.map(esc).join(", ")])}`
		: "";
	return [
		`<div class="alert alert-warning">
			<div>${__("Role {0} gets on {1}: {2}", [role, `<b>${esc(__(doctype))}</b>`, `<b>${added}</b>`])}</div>
			<div>${__("Every user with this role gets it too, users: {0}", [preview.users])}.${profiles}</div>
		</div>`,
		preview.custom
			? ""
			: `<p class="text-muted">${__(
					"The document type uses standard permissions, they are copied to custom permissions first"
			  )}</p>`,
		`<p class="text-muted small">${__(
			"The change is logged in the request and can be revoked from it"
		)}</p>`,
	].join("");
};

erpnext.access_control.role_right_impact = (dialog, options, wrapper) => {
	const role = dialog.get_value("right_role");
	dialog.role_right_preview = null;
	if (!role) {
		wrapper.html(`<p class="text-muted">${__("Choose a role")}</p>`);
		return;
	}
	wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
	const rights = erpnext.access_control.wanted_rights(dialog, options);
	const key = JSON.stringify([role, rights]);
	dialog.role_right_key = key;
	frappe
		.xcall(`${AR_METHOD}.get_role_right_preview`, { name: options.name, role, rights })
		.then((preview) => {
			if (dialog.role_right_key !== key) return;
			dialog.role_right_preview = preview;
			dialog.fetched_coverage = preview.refusal ? null : preview.coverage;
			wrapper.html(erpnext.access_control.role_right_html(preview, options.situation.doctype));
			erpnext.access_control.render_coverage(dialog, options);
		});
};

erpnext.access_control.right_role_options = (options) =>
	options.right_roles.map((entry) => ({
		value: entry.role,
		label: [__(entry.role), __("holders: {0}", [entry.users])].join(" · "),
	}));

erpnext.access_control.revoke_summary = (frm, preview) => {
	const esc = frappe.utils.escape_html;
	const log = preview.log;
	const bold = (text) => `<b>${esc(text)}</b>`;
	const target = bold(`${__(frm.doc.reference_doctype || "")} ${frm.doc.reference_name || ""}`.trim());
	const summaries = {
		"Role Right": () =>
			__(
				"Role {0} loses on {1}: {2}. Every user with this role loses them too. The role itself stays with the user",
				[
					bold(__(log.role)),
					bold(__(log.doctype)),
					log.added.map(erpnext.access_control.right_label).join(", "),
				]
			),
		Role: () =>
			[
				__("The user loses roles: {0}", [log.roles.map((role) => bold(__(role))).join(", ")]),
				log.unlinked.length
					? __("Role profiles unlinked at approval ({0}) are not linked back", [
							log.unlinked.map(esc).join(", "),
					  ])
					: null,
			]
				.filter(Boolean)
				.join("<br>"),
		"Document Share": () =>
			log.previous
				? __("Sharing of {0} goes back to the rights the user had before the request", [target])
				: __("Sharing of {0} with the user is removed", [target]),
		"User Permission": () =>
			log.user_permissions
				.map((entry) =>
					__("User Permission {0} = {1} is removed", [bold(__(entry.allow)), bold(entry.for_value)])
				)
				.join("<br>"),
	};
	return `<div class="alert alert-warning">${summaries[preview.resolution]()}</div>`;
};

erpnext.access_control.revoke_dialog = (frm) =>
	frappe.xcall(`${AR_METHOD}.get_revoke_preview`, { name: frm.doc.name }).then((preview) => {
		const delta = preview.delta;
		const changes = delta
			? erpnext.access_control.tabs_html([
					{
						label: `${__("Loses")} (${delta.lost.doctypes.length})`,
						html: `<p>${__("Roles the user loses")}: ${erpnext.access_control.roles_html(
							delta.lost_roles
						)}</p>${erpnext.access_control.render_grants(delta.lost)}`,
						danger: Boolean(delta.lost_roles.length || delta.lost.doctypes.length),
					},
					{
						label: `${__("Gets")} (${delta.doctypes.length})`,
						html: `<p>${__("Roles the user gets")}: ${erpnext.access_control.roles_html(
							delta.gained_roles
						)}</p>${erpnext.access_control.render_grants(delta)}`,
					},
			  ])
			: "";
		const dialog = new frappe.ui.Dialog({
			title: __("Revoke request {0}", [frm.doc.name]),
			size: delta ? "extra-large" : undefined,
			fields: [
				{ fieldtype: "HTML", fieldname: "summary" },
				{ fieldtype: "Small Text", fieldname: "note", label: __("Note for the user") },
			],
			primary_action_label: __("Revoke"),
			primary_action: ({ note }) =>
				frappe.xcall(`${AR_METHOD}.revoke`, { name: frm.doc.name, note }).then(() => {
					dialog.hide();
					frappe.show_alert({ message: __("Access revoked"), indicator: "orange" });
					frm.reload_doc();
				}),
		});
		const wrapper = dialog.fields_dict.summary.$wrapper;
		wrapper.html(
			erpnext.access_control.STYLE + erpnext.access_control.revoke_summary(frm, preview) + changes
		);
		erpnext.access_control.bind_tabs(wrapper);
		dialog.show();
	});

erpnext.access_control.request_link = (doc) => {
	const routes = {
		"Document Type": () =>
			doc.reference_name
				? frappe.utils.get_form_link(doc.reference_doctype, doc.reference_name)
				: `/desk/${frappe.router.slug(doc.reference_doctype)}`,
		Page: () => `/desk/${encodeURIComponent(doc.page)}`,
		Report: () => `/desk/query-report/${encodeURIComponent(doc.report)}`,
	};
	return routes[doc.request_type] ? routes[doc.request_type]() : null;
};

erpnext.access_control.has_sensitive = (delta) =>
	Boolean(delta && (delta.doctypes || []).some((entry) => entry.sensitive || entry.risky_rights.length));

erpnext.access_control.refresh_impact = (dialog, options) => {
	const wrapper = dialog.fields_dict.impact.$wrapper;
	const resolution = dialog.get_value("resolution");
	dialog.current_delta = null;
	if (resolution === "Document Share") {
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
				"The user can work with documents of these values as well, in every document type that uses them"
			)}</p>`
		);
		return;
	}
	if (resolution === "Role Profile") {
		erpnext.access_control.profile_impact(dialog, options, wrapper);
		return;
	}
	if (resolution === "Role Right") {
		erpnext.access_control.role_right_impact(dialog, options, wrapper);
		return;
	}
	const roles = erpnext.access_control.picked(dialog, "role_list");
	if (!roles.length) {
		wrapper.html(`<p class="text-muted">${__("Choose a role")}</p>`);
		return;
	}
	wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
	const key = JSON.stringify(roles);
	dialog.roles_key = key;
	frappe.xcall(`${AR_METHOD}.get_roles_delta`, { name: options.name, roles }).then((delta) => {
		if (dialog.roles_key !== key) return;
		dialog.current_delta = delta;
		const profile = dialog.get_value("profile_action") || "";
		const profile_note = profile.startsWith("profile:")
			? `<div class="alert alert-warning">${__(
					"The roles are added to role profile {0}, so every user with this profile gets them too",
					[frappe.utils.escape_html(profile.slice("profile:".length))]
			  )}</div>`
			: "";
		wrapper.html(
			erpnext.access_control.STYLE + profile_note + erpnext.access_control.render_grants(delta)
		);
	});
};

erpnext.access_control.impact_state = (dialog) =>
	JSON.stringify([
		...["resolution", "right_role", "profile_action", "share_rights", "profile_mode"].map((fieldname) =>
			dialog.get_value(fieldname)
		),
		...Object.keys(erpnext.access_control.PICK_LISTS).map((fieldname) =>
			erpnext.access_control.picked(dialog, fieldname)
		),
		erpnext.access_control.checked_values(dialog, "value_list"),
	]);

erpnext.access_control.approve_dialog = (frm) =>
	frappe.xcall(`${AR_METHOD}.get_approval_options`, { name: frm.doc.name }).then((options) => {
		const resolutions = erpnext.access_control.resolution_options(options);
		const profiles = erpnext.access_control.profile_options(options.role_profiles);
		const right_roles = erpnext.access_control.right_role_options(options);
		const role_options = erpnext.access_control.role_select_options(options, options.requested_rights);
		const profile_select = erpnext.access_control.profile_select_options(
			options,
			options.requested_rights
		);
		const values = options.user_permissions.map((candidate) => ({
			value: JSON.stringify(candidate),
			label: `${__(candidate.allow)}: ${candidate.for_value}`,
		}));
		let dialog = null;
		const refresh = () => {
			if (!dialog) return;
			const key = erpnext.access_control.impact_state(dialog);
			if (key === dialog.impact_key) return;
			dialog.impact_key = key;
			erpnext.access_control.refresh_impact(dialog, options);
			erpnext.access_control.fetch_coverage(dialog, options);
		};
		dialog = new frappe.ui.Dialog({
			title: __("Approve request {0}", [frm.doc.name]),
			size: "extra-large",
			fields: [
				{ fieldtype: "HTML", fieldname: "situation" },
				{ fieldtype: "Section Break" },
				{
					fieldtype: "MultiCheck",
					fieldname: "rights",
					label: __("Rights to grant"),
					columns: 4,
					sort_options: false,
					select_all: 1,
					on_change: () => dialog && erpnext.access_control.on_rights_change(dialog, options),
					hidden: !options.rights.length,
					description: __(
						"Pre-filled with what the user asked for. Roles and profiles below follow this choice"
					),
					options: options.rights.map((right) => ({
						label: erpnext.access_control.right_label(right),
						value: right,
						checked: options.requested_rights.includes(right),
					})),
				},
				{
					fieldtype: "Select",
					fieldname: "resolution",
					label: __("Grant by"),
					options: resolutions,
					default: resolutions[0].value,
					reqd: 1,
					onchange: refresh,
				},
				{ fieldtype: "HTML", fieldname: "unavailable" },
				erpnext.access_control.pick_list_field("role_list", "Role"),
				{
					fieldtype: "Select",
					fieldname: "right_role",
					label: __("Role to give the rights to"),
					options: right_roles,
					default: right_roles.length ? right_roles[0].value : undefined,
					description: __(
						"The user's roles. Your own roles are not listed unless you are a System Manager"
					),
					depends_on: "eval:doc.resolution==='Role Right'",
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
							checked:
								(options.share_rights || []).includes(right) ||
								options.requested_rights.includes(right),
						})
					),
					depends_on: "eval:doc.resolution==='Document Share'",
					onchange: refresh,
				},
				{
					fieldtype: "HTML",
					fieldname: "value_list",
					depends_on: "eval:doc.resolution==='User Permission'",
				},
				erpnext.access_control.pick_list_field("profile_list", "Role Profile"),
				{
					fieldtype: "Select",
					fieldname: "profile_mode",
					label: __("Current role profiles"),
					options: erpnext.access_control.profile_mode_options(options.role_profiles),
					default: "add",
					hidden: !options.role_profiles.length,
					depends_on: "eval:doc.resolution==='Role Profile'",
					onchange: refresh,
				},
				{ fieldtype: "Section Break", label: __("What the user will get") },
				{ fieldtype: "HTML", fieldname: "coverage" },
				{ fieldtype: "HTML", fieldname: "impact" },
				{ fieldtype: "Section Break" },
				{ fieldtype: "Data", fieldname: "note", label: __("Note for the user") },
			],
			primary_action_label: __("Approve"),
			primary_action(values) {
				const picked = (fieldname) => erpnext.access_control.picked(dialog, fieldname);
				const submit = () =>
					frappe
						.xcall(`${AR_METHOD}.approve`, {
							name: frm.doc.name,
							resolution: values.resolution,
							role: values.right_role,
							roles: picked("role_list"),
							profile_action: values.profile_action,
							profiles: picked("profile_list"),
							profile_mode: values.profile_mode,
							share_rights: values.share_rights,
							rights: options.rights.length ? values.rights || [] : undefined,
							user_permissions: erpnext.access_control
								.checked_values(dialog, "value_list")
								.map((value) => JSON.parse(value)),
							note: values.note,
						})
						.then(() => {
							dialog.hide();
							frappe.show_alert({ message: __("Access granted"), indicator: "green" });
							frm.reload_doc();
						});
				const warnings = erpnext.access_control.approval_warnings(dialog, options, values);
				if (!warnings.length) {
					submit();
					return;
				}
				frappe.confirm(
					`${warnings.map((text) => `<p>${text}</p>`).join("")}<p>${__("Approve anyway?")}</p>`,
					submit
				);
			},
		});
		dialog.fields_dict.situation.$wrapper.html(
			erpnext.access_control.STYLE + erpnext.access_control.situation_html(frm, options)
		);
		erpnext.access_control.set_pick_list(
			dialog,
			"role_list",
			role_options,
			role_options.slice(0, 1).map((option) => option.value)
		);
		erpnext.access_control.set_pick_list(
			dialog,
			"profile_list",
			profile_select,
			profile_select.slice(0, 1).map((option) => option.value)
		);
		Object.keys(erpnext.access_control.PICK_LISTS).forEach((fieldname) =>
			erpnext.access_control.watch_pick_list(dialog, fieldname, refresh)
		);
		erpnext.access_control.render_check_list(
			dialog,
			"value_list",
			values,
			values.map((option) => option.value)
		);
		Object.keys(erpnext.access_control.CHECK_LISTS).forEach((fieldname) =>
			dialog.fields_dict[fieldname].$wrapper.on("change", "input", refresh)
		);
		dialog.fields_dict.unavailable.$wrapper.html(
			erpnext.access_control.unavailable_html(options.unavailable)
		);
		dialog.refetch_role_right = frappe.utils.debounce(
			() => erpnext.access_control.refresh_impact(dialog, options),
			400
		);
		dialog.refetch_candidates = frappe.utils.debounce(
			() => erpnext.access_control.fetch_candidates(dialog, options),
			400
		);
		dialog.fields_dict.share_rights.$wrapper.on("change", "input", () =>
			erpnext.access_control.render_coverage(dialog, options)
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
