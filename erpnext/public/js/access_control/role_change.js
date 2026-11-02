frappe.provide("erpnext.access_control");

erpnext.access_control.role_change = (() => {
	const METHOD = "erpnext.access_control.console";
	const esc = (text) => frappe.utils.escape_html(text);

	const pick_list = (fieldname, label, description) => ({
		fieldtype: "MultiSelectList",
		fieldname,
		label,
		description,
	});

	const fill_pick_list = (dialog, fieldname, items, selected, on_change) => {
		const control = dialog.fields_dict[fieldname];
		control.$list_wrapper.find(".select-all-options").remove();
		control.df.options = items;
		control._options = items;
		control.values = selected;
		control._selected_values = items.filter((item) => selected.includes(item.value));
		const update_status = control.update_status.bind(control);
		control.update_status = () => {
			update_status();
			on_change();
		};
		control.update_status();
	};

	const picked = (dialog, fieldname) => dialog.fields_dict[fieldname].get_value() || [];

	const role_items = (roles) =>
		roles.map((entry) => ({
			value: entry.role,
			label: esc(__(entry.role)),
			description: esc(__("holders: {0}", [entry.users])),
		}));

	const profile_items = (profiles) =>
		profiles.map((profile) => ({
			value: profile.name,
			label: esc(profile.name),
			description: esc(
				[__("users: {0}", [profile.users]), profile.roles.map((role) => __(role)).join(", ")].join(
					" · "
				)
			),
		}));

	const holders_of = (options, names) => options.profiles.filter((profile) => names.includes(profile.name));

	const grant_profile_options = (options) => [
		{ value: "unlink", label: __("Unlink role profiles, keep the roles directly") },
		...holders_of(options, options.current_profiles).map((profile) => ({
			value: `profile:${profile.name}`,
			label: __("Add the roles to profile {0} (users: {1})", [profile.name, profile.users]),
		})),
	];

	const removal_profile_options = (options, role) => {
		const holding = options.profiles.filter((profile) => profile.current && profile.roles.includes(role));
		return [
			{ value: "unlink", label: __("Unlink role profiles, keep the other roles directly") },
			{
				value: "profiles",
				label: __("Remove the role from role profiles {0} (users: {1})", [
					holding.map((profile) => profile.name).join(", "),
					holding.reduce((sum, profile) => sum + profile.users, 0),
				]),
			},
		];
	};

	const profile_mode_options = (options) => {
		const names = options.current_profiles.join(", ");
		return [
			{ value: "add", label: __("Add to the current profiles ({0})", [names]) },
			{ value: "replace", label: __("Replace the current profiles ({0})", [names]) },
		];
	};

	const changes_html = (delta, losing_first) => {
		const gets = {
			label: `${__("Gets")} (${delta.doctypes.length})`,
			html: `<p>${__("Roles the user gets")}: ${erpnext.access_control.roles_html(
				delta.gained_roles
			)}</p>${erpnext.access_control.render_grants(delta)}`,
		};
		const loses = {
			label: `${__("Loses")} (${delta.lost.doctypes.length})`,
			html: delta.lost_roles.length
				? `<p>${__("Roles the user loses")}: ${erpnext.access_control.roles_html(
						delta.lost_roles
				  )}</p>${erpnext.access_control.render_grants(delta.lost)}`
				: `<p class="text-muted">${__("The user loses nothing")}</p>`,
			danger: Boolean(delta.lost_roles.length || delta.lost.doctypes.length),
		};
		return erpnext.access_control.tabs_html(losing_first ? [loses, gets] : [gets, loses]);
	};

	const profile_note = (action) =>
		(action || "").startsWith("profile:")
			? `<div class="alert alert-warning">${__(
					"The roles are added to role profile {0}, so every user with this profile gets them too",
					[esc(action.slice("profile:".length))]
			  )}</div>`
			: action === "profiles"
			? `<div class="alert alert-warning">${__(
					"The role is removed from the role profiles, so every user with these profiles loses it too"
			  )}</div>`
			: "";

	const impact_html = (action, delta, values) =>
		action === "profile"
			? erpnext.access_control.profile_impact_html(delta)
			: profile_note(values.profile_action) + changes_html(delta, action === "remove");

	const watch_impact = (dialog, user, action, args) => {
		const wrapper = dialog.fields_dict.impact.$wrapper;
		const refresh = () => {
			const values = args();
			const key = JSON.stringify(values);
			if (key === dialog.impact_key) return;
			dialog.impact_key = key;
			if (!(values.roles || values.profiles || []).length) {
				wrapper.html(`<p class="text-muted">${__("Choose what to change")}</p>`);
				return;
			}
			wrapper.html(`<p class="text-muted">${__("Loading...")}</p>`);
			frappe.xcall(`${METHOD}.preview_change`, { user, action, ...values }).then((delta) => {
				if (dialog.impact_key !== key) return;
				wrapper.html(
					erpnext.access_control.STYLE + impact_html(action, delta, dialog.get_values(true))
				);
				erpnext.access_control.bind_tabs(wrapper);
			});
		};
		return frappe.utils.debounce(refresh, 300);
	};

	const temporary_fields = (depends_on) => [
		{
			fieldtype: "Datetime",
			fieldname: "valid_till",
			label: __("Valid Till"),
			description: __("Leave empty for permanent access. Temporary access is revoked automatically"),
			depends_on,
		},
	];

	const common_fields = [
		{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason") },
		{ fieldtype: "Section Break", label: __("What changes for the user") },
		{ fieldtype: "HTML", fieldname: "impact" },
	];

	const submit = (dialog, user, action, args, done) => (values) =>
		frappe
			.xcall(`${METHOD}.change_access`, {
				user,
				action,
				reason: values.reason,
				valid_till: values.valid_till,
				...args(),
			})
			.then((result) => {
				dialog.hide();
				frappe.show_alert({
					message: __("Access changed: {0}", [esc(result.title)]),
					indicator: "green",
				});
				done && done(result);
			});

	const open = (user, build) =>
		frappe.xcall(`${METHOD}.get_change_options`, { user: user.user }).then((options) => build(options));

	const grant = (user, done) =>
		open(user, (options) => {
			const profiles = options.current_profiles.length ? grant_profile_options(options) : [];
			let dialog = null;
			const args = () => ({
				roles: picked(dialog, "roles"),
				profile_action: dialog.get_value("profile_action"),
			});
			dialog = new frappe.ui.Dialog({
				title: __("Grant roles to {0}", [esc(user.full_name || user.user)]),
				size: "extra-large",
				fields: [
					pick_list("roles", __("Roles"), __("Roles the user does not have yet")),
					{
						fieldtype: "Select",
						fieldname: "profile_action",
						label: __("Role profile"),
						options: profiles,
						default: profiles.length ? "unlink" : undefined,
						hidden: !profiles.length,
						description: __(
							"While the user has a role profile, a role added directly is removed on the next save"
						),
						onchange: () => dialog && refresh(),
					},
					...temporary_fields("eval:!doc.profile_action || doc.profile_action==='unlink'"),
					...common_fields,
				],
				primary_action_label: __("Grant"),
			});
			const refresh = watch_impact(dialog, user.user, "grant", args);
			dialog.set_primary_action(__("Grant"), submit(dialog, user.user, "grant", args, done));
			fill_pick_list(dialog, "roles", role_items(options.grantable), [], refresh);
			dialog.show();
			refresh();
		});

	const remove = (user, role, done) =>
		open(user, (options) => {
			const profiles = options.current_profiles.length ? removal_profile_options(options, role) : [];
			let dialog = null;
			const args = () => ({ roles: [role], profile_action: dialog.get_value("profile_action") });
			dialog = new frappe.ui.Dialog({
				title: __("Remove role {0} from {1}", [esc(__(role)), esc(user.full_name || user.user)]),
				size: "extra-large",
				fields: [
					{
						fieldtype: "Select",
						fieldname: "profile_action",
						label: __("Role profile"),
						options: profiles,
						default: profiles.length ? "unlink" : undefined,
						hidden: !profiles.length,
						description: __("The role comes from the user's role profile"),
						onchange: () => dialog && refresh(),
					},
					...common_fields,
				],
			});
			const refresh = watch_impact(dialog, user.user, "remove", args);
			dialog.set_primary_action(__("Remove role"), submit(dialog, user.user, "remove", args, done));
			dialog.get_primary_btn().removeClass("btn-primary").addClass("btn-danger");
			dialog.show();
			refresh();
		});

	const profiles = (user, done) =>
		open(user, (options) => {
			const has_current = Boolean(options.current_profiles.length);
			const offered = options.profiles.filter((profile) => !profile.privileged);
			let dialog = null;
			const args = () => ({
				profiles: picked(dialog, "profiles"),
				profile_mode: dialog.get_value("profile_mode") || "add",
			});
			dialog = new frappe.ui.Dialog({
				title: __("Role profiles of {0}", [esc(user.full_name || user.user)]),
				size: "extra-large",
				fields: [
					pick_list(
						"profiles",
						__("Role Profiles"),
						__("Profiles with System Manager or Access Manager roles are not offered")
					),
					{
						fieldtype: "Select",
						fieldname: "profile_mode",
						label: __("Current role profiles"),
						options: has_current ? profile_mode_options(options) : [],
						default: "add",
						hidden: !has_current,
						onchange: () => dialog && refresh(),
					},
					...common_fields,
				],
			});
			const refresh = watch_impact(dialog, user.user, "profile", args);
			dialog.set_primary_action(__("Assign"), submit(dialog, user.user, "profile", args, done));
			fill_pick_list(dialog, "profiles", profile_items(offered), [], refresh);
			dialog.show();
			refresh();
		});

	return { grant, remove, profiles };
})();
