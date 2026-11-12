(() => {
	const settings = (frappe.listview_settings["Activity Log"] =
		frappe.listview_settings["Activity Log"] || {});
	const esc = frappe.utils.escape_html;
	const LOGOUT_REASON = /<(?:strong|b)>(.*?)<\/(?:strong|b)>/;
	const VIEW_REASON = /(?:Reason|Причина):\s*(.*)$/s;

	const event_text = (doc) => {
		if (doc.operation === "Login") return doc.status === "Failed" ? __("Failed Login") : __("Login");
		if (doc.operation === "Logout") {
			const reason = (doc.subject || "").match(LOGOUT_REASON)?.[1];
			return reason ? `${__("Signed Out")} · ${__(reason)}` : __("Signed Out");
		}
		if (doc.operation === "Impersonate") {
			const reason = (doc.subject || "").match(VIEW_REASON)?.[1];
			return reason
				? `${__("Viewing as another user")} · ${__("Started")} · ${reason}`
				: `${__("Viewing as another user")} · ${__("Finished")}`;
		}
		return frappe.utils.html2text(doc.subject || "");
	};

	const set_tooltips = (listview) => {
		const by_name = Object.fromEntries(listview.data.map((doc) => [doc.name, doc]));
		listview.$result.find(".list-subject a[data-name]").each((i, link) => {
			const doc = by_name[link.dataset.name];
			if (doc) link.title = frappe.utils.html2text(doc.subject || "");
		});
	};

	const onload = settings.onload;
	settings.onload = (listview) => {
		onload?.(listview);
		erpnext.entity.bind_list_links(listview);
		const render = listview.render.bind(listview);
		listview.render = (...args) => {
			render(...args);
			set_tooltips(listview);
		};
	};

	const refresh = settings.refresh;
	settings.refresh = (listview) => {
		refresh?.(listview);
		erpnext.entity
			.load_users(listview.data.flatMap((doc) => [doc.user, doc.owner]))
			.then((loaded) => loaded && listview.render());
	};

	settings.hide_name_column = true;
	settings.add_fields = [
		...(settings.add_fields || []),
		"subject",
		"operation",
		"status",
		"user",
		"owner",
		"ip_address",
	];
	settings.get_form_link = (doc) =>
		doc.user
			? frappe.utils.get_form_link("User", doc.user)
			: `/desk/activity-log/${encodeURIComponent(doc.name)}`;
	settings.formatters = {
		...settings.formatters,
		subject: (value, df, doc) => event_text(doc),
		user(value, df, doc) {
			if (!value) return "";
			const target = erpnext.entity.user(value, { size: 20 });
			if (doc.operation !== "Impersonate" || !doc.owner || doc.owner === value) return target;
			return `<span class="ent-list">${erpnext.entity.user(doc.owner, {
				size: 20,
			})} <i class="fa fa-long-arrow-right text-muted"></i> ${target}</span>`;
		},
		ip_address: (value) =>
			value
				? `<a class="filterable ellipsis" data-filter="ip_address,=,${esc(value)}">${esc(value)}</a>`
				: "",
	};
})();
