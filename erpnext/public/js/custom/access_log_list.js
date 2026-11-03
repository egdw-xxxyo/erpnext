(() => {
	const settings = (frappe.listview_settings["Access Log"] = frappe.listview_settings["Access Log"] || {});
	const esc = frappe.utils.escape_html;
	const files = {};
	const protected_objects = () => frappe.boot.sensitive_data?.objects || {};
	const is_protected = (doc) =>
		(protected_objects().doctypes || []).includes(source_doctype(doc)) ||
		(protected_objects().reports || []).includes(doc.report_name);

	const file_of = (doc) => (doc.export_from === "File" && files[doc.reference_document]) || null;
	const source_doctype = (doc) =>
		file_of(doc)?.attached_to_doctype || (doc.export_from !== "File" && doc.export_from);

	const action = (doc) => {
		if (doc.method === "Print") return "Print";
		if (doc.method === "PDF") return "PDF";
		if (doc.export_from === "File" || doc.report_name === "Backup") return "File Download";
		return "Export";
	};

	const object_label = (doc) => {
		const file = file_of(doc);
		if (file) return file.file_name || doc.reference_document;
		if (doc.report_name) return __(doc.report_name);
		if (doc.reference_document) return doc.reference_document;
		return doc.export_from ? __(doc.export_from) : doc.name;
	};

	const query_string = (filters) => {
		const params = Object.entries(filters || {})
			.filter(([, value]) => value !== null && value !== undefined && value !== "")
			.map(([key, value]) => [key, Array.isArray(value) ? JSON.stringify(value) : value]);
		return params.length ? `?${new URLSearchParams(params)}` : "";
	};

	const report_link = (doc) => {
		if (doc.report_name.includes("/")) return `/desk/${doc.report_name}`;
		let filters = {};
		try {
			filters = JSON.parse(doc.filters || "{}");
		} catch (e) {
			filters = {};
		}
		return `/desk/query-report/${encodeURIComponent(doc.report_name)}${query_string(filters)}`;
	};

	const load_files = (listview) => {
		const names = [
			...new Set(
				listview.data
					.filter((doc) => doc.export_from === "File" && doc.reference_document)
					.map((doc) => doc.reference_document)
					.filter((name) => !(name in files))
			),
		];
		if (!names.length) return Promise.resolve(false);
		names.forEach((name) => (files[name] = null));
		return frappe.db
			.get_list("File", {
				filters: { name: ["in", names] },
				fields: ["name", "file_name", "attached_to_doctype", "attached_to_name"],
				limit: names.length,
			})
			.then((rows) => {
				rows.forEach((row) => (files[row.name] = row));
				return rows.length > 0;
			});
	};

	const onload = settings.onload;
	settings.onload = (listview) => {
		onload?.(listview);
		erpnext.entity.bind_list_links(listview);
	};

	const refresh = settings.refresh;
	settings.refresh = (listview) => {
		refresh?.(listview);
		Promise.all([
			erpnext.entity.load_users(listview.data.map((doc) => doc.user)),
			load_files(listview),
		]).then((loaded) => loaded.some(Boolean) && listview.render());
	};

	settings.hide_name_column = true;
	settings.add_fields = [
		...(settings.add_fields || []),
		"user",
		"export_from",
		"reference_document",
		"report_name",
		"file_type",
		"method",
		"filters",
	];

	settings.get_form_link = (doc) => {
		const file = file_of(doc);
		if (file?.attached_to_doctype && file.attached_to_name)
			return frappe.utils.get_form_link(file.attached_to_doctype, file.attached_to_name);
		if (doc.report_name && doc.report_name !== "Backup") return report_link(doc);
		if (doc.export_from && doc.reference_document)
			return frappe.utils.get_form_link(doc.export_from, doc.reference_document);
		if (doc.export_from && doc.export_from !== "File")
			return `/desk/${frappe.router.slug(doc.export_from)}/view/report`;
		return `/desk/access-log/${encodeURIComponent(doc.name)}`;
	};

	settings.formatters = {
		...settings.formatters,
		reference_document: (value, df, doc) => object_label(doc),
		user: (value) => (value ? erpnext.entity.user(value, { size: 20 }) : ""),
		method: (value, df, doc) => esc(__(action(doc))),
		export_from(value, df, doc) {
			const source = source_doctype(doc) || (doc.report_name && "Report");
			if (!source) return "";
			const lock = is_protected(doc)
				? `<i class="fa fa-lock text-warning" title="${__("Protected data")}"></i> `
				: "";
			return `<span class="ellipsis">${lock}${esc(__(source))}</span>`;
		},
	};
})();
