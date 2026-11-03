(() => {
	const settings = (frappe.listview_settings["Permission Log"] =
		frappe.listview_settings["Permission Log"] || {});
	const PL = erpnext.permission_log;

	const set_tooltips = (listview) => {
		const by_name = Object.fromEntries(listview.data.map((doc) => [doc.name, doc]));
		listview.$result.find(".list-subject a[data-name]").each((i, link) => {
			const doc = by_name[link.dataset.name];
			if (doc) link.title = PL.describe(doc).full;
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
		const users = listview.data.flatMap(PL.users_of);
		Promise.all([erpnext.entity.load_users(users), PL.load_roles(listview.data)]).then(
			(loaded) => loaded.some(Boolean) && listview.render()
		);
	};

	settings.hide_name_column = true;
	settings.add_fields = [
		...(settings.add_fields || []),
		"changes",
		"changed_by",
		"for_doctype",
		"for_document",
		"reference_type",
		"reference",
		"status",
	];
	settings.formatters = {
		...settings.formatters,
		changes: (value, df, doc) => PL.describe(doc).short,
		changed_by: (value) => (value ? erpnext.entity.user(value, { size: 20 }) : ""),
		for_document: (value, df, doc) => (value ? PL.object_html(doc) : ""),
	};
})();
