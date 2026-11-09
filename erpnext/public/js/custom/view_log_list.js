(() => {
	const settings = (frappe.listview_settings["View Log"] = frappe.listview_settings["View Log"] || {});
	const is_protected = (doctype) => (frappe.boot.sensitive_data?.objects?.doctypes || []).includes(doctype);

	const onload = settings.onload;
	settings.onload = (listview) => {
		onload?.(listview);
		erpnext.entity.bind_list_links(listview);
	};

	const refresh = settings.refresh;
	settings.refresh = (listview) => {
		refresh?.(listview);
		erpnext.entity
			.load_users(listview.data.map((doc) => doc.viewed_by))
			.then((loaded) => loaded && listview.render());
	};

	settings.hide_name_column = true;
	settings.add_fields = [
		...(settings.add_fields || []),
		"viewed_by",
		"reference_doctype",
		"reference_name",
	];
	settings.get_form_link = (doc) =>
		doc.reference_doctype && doc.reference_name
			? frappe.utils.get_form_link(doc.reference_doctype, doc.reference_name)
			: `/desk/view-log/${encodeURIComponent(doc.name)}`;
	settings.formatters = {
		...settings.formatters,
		viewed_by: (value) => (value ? erpnext.entity.user(value, { size: 20 }) : ""),
		reference_doctype(value) {
			const lock = is_protected(value)
				? `<i class="fa fa-lock text-warning" title="${__("Protected data")}"></i> `
				: "";
			return `<a class="filterable ellipsis" data-filter="reference_doctype,=,${frappe.utils.escape_html(
				value
			)}">${lock}${frappe.utils.escape_html(__(value))}</a>`;
		},
	};
})();
