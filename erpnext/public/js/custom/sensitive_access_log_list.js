(() => {
	const settings = (frappe.listview_settings["Sensitive Access Log"] =
		frappe.listview_settings["Sensitive Access Log"] || {});
	const esc = frappe.utils.escape_html;
	const log = erpnext.sensitive_log;

	const set_tooltips = (listview) => {
		const by_name = Object.fromEntries(listview.data.map((doc) => [doc.name, doc]));
		listview.$result.find(".list-subject a[data-name]").each((i, link) => {
			const doc = by_name[link.dataset.name];
			if (doc) link.title = log.tooltip(doc);
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
			.load_users(listview.data.flatMap((doc) => [doc.user, doc.actor]))
			.then((loaded) => loaded && listview.render());
	};

	settings.hide_name_column = true;
	settings.add_fields = [
		...(settings.add_fields || []),
		"event",
		"user",
		"actor",
		"expires_on",
		"ip_address",
		"user_agent",
		"details",
		"creation",
	];
	settings.get_indicator = (doc) => [log.label(doc.event), log.color(doc.event), `event,=,${doc.event}`];
	settings.get_form_link = (doc) =>
		doc.event === "Settings Changed"
			? "/desk/sensitive-data-settings"
			: frappe.utils.get_form_link("User", doc.user);
	settings.formatters = {
		...settings.formatters,
		event: (value, df, doc) => log.describe(doc).short,
		user(value, df, doc) {
			if (!value) return "";
			const target = erpnext.entity.user(value, { size: 20 });
			if (!doc.actor || doc.actor === value) return target;
			return `<span class="ent-list">${erpnext.entity.user(doc.actor, {
				size: 20,
			})} <i class="fa fa-long-arrow-right text-muted"></i> ${target}</span>`;
		},
		ip_address: (value) =>
			value
				? `<a class="filterable ellipsis" data-filter="ip_address,=,${esc(value)}">${esc(value)}</a>`
				: "",
	};
})();
