frappe.pages["access-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Access Management"),
		single_column: true,
	});
	wrapper.access_console = new AccessConsole(page);
};

frappe.pages["access-console"].on_page_show = function (wrapper) {
	wrapper.access_console?.load();
};

const CONSOLE_METHOD = "erpnext.access_control.console";
const PSEUDO_ROLES = ["All", "Desk User"];
const NO_EMPLOYEE = "__none__";
const INACTIVE_DAYS = 30;

const QUICK_FILTERS = {
	no_profile: { label: () => __("No role profile"), test: (user) => !user.profiles.length },
	temporary: {
		label: () => __("Temporary access"),
		test: (user) => Object.keys(user.temporary).length > 0,
	},
	system_manager: {
		label: () => __("System Manager"),
		test: (user) => user.roles.includes("System Manager"),
	},
	inactive: {
		label: () => __("No login for {0}+ days", [INACTIVE_DAYS]),
		test: (user) =>
			Boolean(user.last_login) &&
			frappe.datetime.get_day_diff(frappe.datetime.now_date(), user.last_login) > INACTIVE_DAYS,
	},
	never: { label: () => __("Never logged in"), test: (user) => !user.last_login },
	pending: { label: () => __("Pending requests"), test: (user) => user.pending > 0 },
};

const count_by = (values) =>
	values.reduce((counts, value) => ({ ...counts, [value]: (counts[value] || 0) + 1 }), {});

const select_options = (all_label, counts, label = (value) => value) => [
	{ value: "", label: all_label },
	...Object.keys(counts)
		.sort((a, b) => label(a).localeCompare(label(b)))
		.map((value) => ({ value, label: `${label(value)} (${counts[value]})` })),
];

class AccessConsole {
	constructor(page) {
		this.page = page;
		this.users = [];
		this.open = new Set();
		this.quick = new Set();
		this.who = null;
		this.protected_roles = ["Administrator", "System Manager", "Access Manager"];
		const render = () => this.render();
		this.search = page.add_field({
			fieldtype: "Data",
			fieldname: "search",
			label: __("Search"),
			placeholder: __("Name, email or role"),
			change: render,
		});
		this.search.$input.on("input", frappe.utils.debounce(render, 200));
		this.role = page.add_field({
			fieldtype: "Select",
			fieldname: "role",
			label: __("Role"),
			change: render,
		});
		this.profile = page.add_field({
			fieldtype: "Select",
			fieldname: "profile",
			label: __("Role Profile"),
			change: render,
		});
		this.company = page.add_field({
			fieldtype: "Select",
			fieldname: "company",
			label: __("Company"),
			change: render,
		});
		this.who_doctype = page.add_field({
			fieldtype: "Link",
			fieldname: "who_doctype",
			label: __("Who can: document type"),
			options: "DocType",
			get_query: () => ({ filters: { istable: 0 } }),
			change: () => this.load_rights(),
		});
		this.who_right = page.add_field({
			fieldtype: "Select",
			fieldname: "who_right",
			label: __("Right"),
			change: () => this.load_who(),
		});
		page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.$body = $('<div class="ac-console"></div>').appendTo(page.main);
		this.add_style();
		this.bind();
	}

	load() {
		return frappe.xcall("erpnext.access_control.impersonation.get_users").then((users) => {
			this.users = users;
			this.fill_filters();
			this.render();
		});
	}

	set_options(field, options) {
		const value = field.get_value();
		field.df.options = options;
		field.refresh();
		field.set_input(options.some((option) => option.value === value) ? value : "");
	}

	fill_filters() {
		const users = this.users;
		this.set_options(
			this.role,
			select_options(__("All roles"), count_by(users.flatMap((user) => user.roles)), __)
		);
		this.set_options(
			this.profile,
			select_options(__("All role profiles"), count_by(users.flatMap((user) => user.profiles)))
		);
		this.set_options(
			this.company,
			select_options(
				__("All companies"),
				count_by(users.map((user) => (user.employee && user.employee.company) || NO_EMPLOYEE)),
				(value) => (value === NO_EMPLOYEE ? __("No employee") : value)
			)
		);
	}

	load_rights() {
		const doctype = this.who_doctype.get_value();
		this.who = null;
		if (!doctype) {
			this.set_options(this.who_right, []);
			this.render();
			return;
		}
		frappe.xcall(`${CONSOLE_METHOD}.get_doctype_rights`, { doctype }).then((rights) => {
			this.set_options(this.who_right, [
				{ value: "", label: __("Choose a right") },
				...rights.map((right) => ({
					value: right,
					label: erpnext.access_control.right_label(right),
				})),
			]);
			this.who_right.set_input(rights.includes("read") ? "read" : "");
			this.load_who();
		});
	}

	load_who() {
		const doctype = this.who_doctype.get_value();
		const right = this.who_right.get_value();
		if (!doctype || !right) {
			this.who = null;
			this.render();
			return;
		}
		frappe.xcall(`${CONSOLE_METHOD}.who_can`, { doctype, right }).then((roles) => {
			this.who = { doctype, right, roles };
			this.render();
		});
	}

	who_roles(user) {
		if (!this.who) return [];
		const held = [...user.roles, ...PSEUDO_ROLES];
		return Object.keys(this.who.roles).filter((role) => held.includes(role));
	}

	matches(user, words) {
		const employee = user.employee || {};
		const haystack = [
			user.full_name,
			user.user,
			...user.roles.map(__),
			...user.roles,
			...user.profiles,
			employee.company,
			employee.department,
			employee.employee_name,
		]
			.filter(Boolean)
			.join(" ")
			.toLowerCase();
		return words.every((word) => haystack.includes(word));
	}

	filtered() {
		const words = (this.search.get_value() || "").toLowerCase().split(/\s+/).filter(Boolean);
		const role = this.role.get_value();
		const profile = this.profile.get_value();
		const company = this.company.get_value();
		return this.users.filter(
			(user) =>
				this.matches(user, words) &&
				(!role || user.roles.includes(role)) &&
				(!profile || user.profiles.includes(profile)) &&
				(!company || ((user.employee && user.employee.company) || NO_EMPLOYEE) === company) &&
				(!this.who || this.who_roles(user).length > 0)
		);
	}

	visible(users) {
		return users.filter((user) => [...this.quick].every((key) => QUICK_FILTERS[key].test(user)));
	}

	has_filters() {
		return Boolean(
			this.search.get_value() ||
				this.role.get_value() ||
				this.profile.get_value() ||
				this.company.get_value() ||
				this.who_doctype.get_value() ||
				this.quick.size
		);
	}

	reset_filters() {
		[this.search, this.role, this.profile, this.company, this.who_doctype].forEach((field) =>
			field.set_input("")
		);
		this.set_options(this.who_right, []);
		this.who = null;
		this.quick = new Set();
		this.render();
	}

	filter_by(field, value) {
		field.set_input(value);
		this.render();
		frappe.utils.scroll_to(this.page.wrapper, true);
	}

	quick_html(users) {
		const chips = Object.entries(QUICK_FILTERS)
			.map(([key, filter]) => {
				const count = users.filter(filter.test).length;
				const active = this.quick.has(key);
				return `<button class="btn btn-xs ${active ? "btn-primary" : "btn-default"} ac-quick-filter"
					data-key="${key}" ${count || active ? "" : "disabled"}>${filter.label()} · ${count}</button>`;
			})
			.join("");
		const reset = this.has_filters() ? `<a class="ac-reset">${__("Reset filters")}</a>` : "";
		return `<div class="ac-quick">${chips}${reset}</div>`;
	}

	who_note() {
		if (!this.who) return "";
		const roles = Object.keys(this.who.roles);
		return `<div class="ac-who-note text-muted">${__("Who can {0} {1}: roles {2}", [
			`<b>${frappe.utils.escape_html(erpnext.access_control.right_label(this.who.right))}</b>`,
			`<b>${frappe.utils.escape_html(__(this.who.doctype))}</b>`,
			roles.length ? roles.map((role) => frappe.utils.escape_html(__(role))).join(", ") : "—",
		])}</div>`;
	}

	render() {
		const filtered = this.filtered();
		const users = this.visible(filtered);
		this.$body.html(
			`${this.quick_html(filtered)}${this.who_note()}${
				users.length
					? `<div class="ac-count text-muted">${__("{0} users", [users.length])}</div>${users
							.map((user) => this.row_html(user))
							.join("")}`
					: `<div class="text-muted ac-empty">${__("No users found")}</div>`
			}`
		);
	}

	who_badge(user) {
		const roles = this.who_roles(user);
		if (!roles.length) return "";
		const own_only = roles.every((role) => this.who.roles[role] === "owner");
		const names = roles.map((role) => __(role)).join(", ");
		return `<span class="indicator-pill green no-indicator-dot ac-who" title="${frappe.utils.escape_html(
			names
		)}"><i class="fa fa-key"></i>&nbsp;${frappe.utils.escape_html(
			own_only ? __("own only, via {0}", [names]) : __("via {0}", [names])
		)}</span>`;
	}

	org_html(user) {
		const employee = user.employee;
		if (!employee) return "";
		const parts = [employee.company, employee.department].filter(Boolean);
		return `<div class="ac-user-org text-muted">${frappe.utils.escape_html(parts.join(" · "))}</div>`;
	}

	pending_html(user) {
		if (!user.pending) return "";
		return `<a class="indicator-pill orange no-indicator-dot ac-pending" href="/desk/access-request?user=${encodeURIComponent(
			user.user
		)}&status=Pending" title="${frappe.utils.escape_html(__("Pending requests"))}">
			<i class="fa fa-inbox"></i>&nbsp;${user.pending}</a>`;
	}

	row_html(user) {
		const expanded = this.open.has(user.user);
		const profiles = user.profiles
			.map(
				(name) =>
					`<span class="indicator-pill blue no-indicator-dot ac-profile" data-profile="${frappe.utils.escape_html(
						name
					)}" title="${frappe.utils.escape_html(
						__("Show users with this role profile")
					)}"><i class="fa fa-id-badge"></i>&nbsp;${frappe.utils.escape_html(name)}</span>`
			)
			.join("");
		const last_login = user.last_login
			? frappe.datetime.prettyDate(user.last_login)
			: __("Never logged in");
		const disabled = user.refusal ? `disabled title="${frappe.utils.escape_html(user.refusal)}"` : "";
		return `
			<div class="ac-user ${expanded ? "expanded" : ""}" data-user="${frappe.utils.escape_html(user.user)}">
				<div class="ac-user-main">
					<i class="fa fa-chevron-${expanded ? "down" : "right"} text-muted ac-chevron"></i>
					<div class="ac-user-who">${erpnext.entity.user(
						{ user: user.user, full_name: user.full_name, user_image: user.user_image },
						{ size: 28, sub: user.user }
					)}</div>
					${this.org_html(user)}
					<div class="ac-user-profiles">${this.who_badge(user)}${profiles}</div>
					${this.pending_html(user)}
					<div class="ac-user-roles-count text-muted">${__("{0} roles", [user.roles.length])}</div>
					<div class="ac-user-login text-muted">${last_login}</div>
					<button class="btn btn-xs btn-default ac-view" ${disabled}>
						<i class="fa fa-eye"></i> ${__("View as...")}
					</button>
				</div>
				${expanded ? this.roles_html(user) : ""}
			</div>`;
	}

	role_chip(user, role) {
		const esc = frappe.utils.escape_html;
		const till = user.temporary[role];
		const temporary = till
			? `<i class="fa fa-clock-o ac-temporary" title="${esc(
					__("Temporary, until {0}", [frappe.datetime.str_to_user(till)])
			  )}"></i>`
			: "";
		const removable = !user.manage_refusal && !this.protected_roles.includes(role);
		const remove = removable
			? `<span class="ac-role-remove" data-role="${esc(role)}" title="${esc(
					__("Remove role")
			  )}"><i class="fa fa-times"></i></span>`
			: "";
		const sources = (user.role_sources || {})[role] || [];
		const source = sources.length
			? `<span class="ac-role-source" title="${esc(
					__("From role profile: {0}", [sources.join(", ")])
			  )}"><i class="fa fa-id-badge"></i> ${esc(sources.join(", "))}</span>`
			: "";
		return `<span class="ac-role-chip">
			<button class="btn btn-xs btn-default ac-role" data-role="${esc(role)}"
				title="${esc(__("What this role grants"))}">${temporary}${esc(__(role))}${source}</button>${remove}
		</span>`;
	}

	actions_html(user) {
		if (user.manage_refusal) {
			return `<div class="text-muted small ac-refusal"><i class="fa fa-lock"></i> ${frappe.utils.escape_html(
				user.manage_refusal
			)}</div>`;
		}
		return `<div class="ac-actions">
			<button class="btn btn-xs btn-default ac-grant"><i class="fa fa-plus"></i> ${__("Grant roles")}</button>
			<button class="btn btn-xs btn-default ac-profiles"><i class="fa fa-id-badge"></i> ${__(
				"Role profiles"
			)}</button>
		</div>`;
	}

	roles_html(user) {
		const chips = user.roles.map((role) => this.role_chip(user, role)).join("");
		const refusal = user.refusal
			? `<div class="text-muted small ac-refusal"><i class="fa fa-eye-slash"></i> ${frappe.utils.escape_html(
					user.refusal
			  )}</div>`
			: "";
		return `<div class="ac-user-roles">${
			chips || `<span class="text-muted">${__("No roles")}</span>`
		}${this.actions_html(user)}${refusal}</div>`;
	}

	user_of(element) {
		const name = $(element).closest(".ac-user").attr("data-user");
		return this.users.find((user) => user.user === name);
	}

	bind() {
		this.$body.on("click", ".ac-user-main", (event) => {
			if ($(event.target).closest("a[href], button, .ac-profile").length) return;
			const user = this.user_of(event.currentTarget);
			this.open.has(user.user) ? this.open.delete(user.user) : this.open.add(user.user);
			this.render();
		});
		this.$body.on("click", ".ac-view", (event) => {
			const user = this.user_of(event.currentTarget);
			erpnext.access_control.view_session.start(user.user, user.full_name);
		});
		this.$body.on("click", ".ac-role", (event) =>
			erpnext.access_control.show_role_grants($(event.currentTarget).attr("data-role"), (role) =>
				this.filter_by(this.role, role)
			)
		);
		this.$body.on("click", ".ac-profile", (event) =>
			this.filter_by(this.profile, $(event.currentTarget).attr("data-profile"))
		);
		this.$body.on("click", ".ac-quick-filter", (event) => {
			const key = $(event.currentTarget).attr("data-key");
			this.quick.has(key) ? this.quick.delete(key) : this.quick.add(key);
			this.render();
		});
		this.$body.on("click", ".ac-reset", () => this.reset_filters());
		const reload = () => this.load();
		this.$body.on("click", ".ac-role-remove", (event) =>
			erpnext.access_control.role_change.remove(
				this.user_of(event.currentTarget),
				$(event.currentTarget).attr("data-role"),
				reload
			)
		);
		this.$body.on("click", ".ac-grant", (event) =>
			erpnext.access_control.role_change.grant(this.user_of(event.currentTarget), reload)
		);
		this.$body.on("click", ".ac-profiles", (event) =>
			erpnext.access_control.role_change.profiles(this.user_of(event.currentTarget), reload)
		);
	}

	add_style() {
		if (document.getElementById("access-console-style")) return;
		const style = document.createElement("style");
		style.id = "access-console-style";
		style.textContent = `
			.ac-console { padding: var(--padding-md) 0; }
			.ac-count, .ac-empty { padding: 0 var(--padding-md) var(--padding-sm); font-size: var(--text-sm); }
			.ac-quick {
				display: flex;
				flex-wrap: wrap;
				align-items: center;
				gap: 6px;
				padding: 0 var(--padding-md) var(--padding-md);
			}
			.ac-reset { margin-left: var(--margin-sm); font-size: var(--text-sm); cursor: pointer; }
			.ac-who-note { padding: 0 var(--padding-md) var(--padding-sm); font-size: var(--text-sm); }
			.ac-user-org { font-size: var(--text-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 260px; }
			.ac-profile { cursor: pointer; }
			.ac-pending { text-decoration: none; }
			.ac-user { border-top: 1px solid var(--border-color); }
			.ac-user-main {
				display: flex;
				align-items: center;
				gap: var(--margin-md);
				padding: var(--padding-sm) var(--padding-md);
				cursor: pointer;
			}
			.ac-user-main:hover { background-color: var(--subtle-fg); }
			.ac-chevron { width: 10px; }
			.ac-user-who { flex: 1 1 auto; min-width: 0; }
			.ac-user-profiles { display: flex; flex-wrap: wrap; gap: 4px; }
			.ac-user-roles-count, .ac-user-login { font-size: var(--text-sm); white-space: nowrap; }
			.ac-user-roles {
				display: flex;
				flex-wrap: wrap;
				gap: 6px;
				padding: var(--padding-sm) var(--padding-md) var(--padding-md) calc(var(--padding-md) + 26px);
			}
			.ac-user-roles .ac-role,
			.ac-user-profiles .indicator-pill {
				display: inline-flex;
				align-items: center;
				height: 24px;
				padding: 0 var(--padding-sm);
				line-height: 1;
			}
			.ac-refusal { flex-basis: 100%; margin-top: var(--margin-xs); }
			.ac-role-chip { display: inline-flex; align-items: center; }
			.ac-role-chip .ac-role { gap: 4px; }
			.ac-role-chip .ac-role-remove + .ac-role, .ac-role-chip .ac-role:has(+ .ac-role-remove) {
				border-top-right-radius: 0;
				border-bottom-right-radius: 0;
			}
			.ac-role-remove {
				display: inline-flex;
				align-items: center;
				height: 24px;
				padding: 0 6px;
				border-left: 1px solid var(--border-color);
				border-radius: 0 var(--border-radius-sm) var(--border-radius-sm) 0;
				background-color: var(--control-bg);
				color: var(--text-muted);
				cursor: pointer;
				box-shadow: var(--btn-shadow);
			}
			.ac-role-remove:hover { color: var(--red-500); }
			.ac-temporary { color: var(--orange-500); }
			.ac-role-source { color: var(--blue-500); font-size: var(--text-xs); }
			.ac-actions { display: flex; gap: 6px; flex-basis: 100%; margin-top: var(--margin-xs); }
			@media (max-width: 767px) {
				.ac-user-main { flex-wrap: wrap; }
				.ac-user-login { display: none; }
			}
		`;
		document.head.appendChild(style);
	}
}
