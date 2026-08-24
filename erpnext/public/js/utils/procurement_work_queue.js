frappe.provide("erpnext.buying");

erpnext.buying.get_procurement_status_color = (status) =>
	({
		Підготовка: "gray",
		Погодження: "orange",
		"Очікує оплату": "blue",
		"Очікує надходження": "purple",
		Завершено: "green",
	})[status] || "gray";

erpnext.buying.format_procurement_status = (status, fieldname = "procurement_completion_status") => {
	if (!status) return "";
	const escaped_status = frappe.utils.escape_html(status);
	const color = erpnext.buying.get_procurement_status_color(status);
	return `<span class="filterable indicator-pill ${color} ellipsis" title="${escaped_status}"
		data-filter="${fieldname},=,${escaped_status}"><span class="ellipsis">${__(
		status
	)}</span></span>`;
};

erpnext.buying.apply_procurement_work_queue_filters = (listview, options) => {
	if (listview.__procurement_work_queue_filters_applied) {
		return;
	}
	listview.__procurement_work_queue_filters_applied = true;

	const participant = frappe.session.user;
	const filters = [
		[listview.doctype, options.participants_field, "like", `%\"${participant}\"%`],
		[
			listview.doctype,
			options.completion_field,
			"!=",
			options.completion_value || "Завершено",
		],
	];

	// These are working-list defaults, not permission restrictions. Clearing them
	// exposes history for the current visit; opening/reloading the list restores them.
	setTimeout(() => {
		listview.filter_area
			.clear(false)
			.then(() => listview.filter_area.set(filters))
			.then(() => {
				listview.start = 0;
				return listview.refresh();
			});
	}, 0);
};
