frappe.provide("erpnext.buying");

erpnext.buying.apply_procurement_work_queue_filters = (listview, options) => {
	if (listview.__procurement_work_queue_filters_applied) {
		return;
	}
	listview.__procurement_work_queue_filters_applied = true;

	const participant = frappe.session.user;
	const filters = [
		[listview.doctype, options.participants_field, "like", `%\"${participant}\"%`],
		[listview.doctype, options.completion_field, "!=", "Completed"],
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
