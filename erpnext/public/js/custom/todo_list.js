// Extend Frappe's ToDo list without replacing its reference-document action.
(() => {
	const settings = frappe.listview_settings["ToDo"];
	const onload = settings.onload;
	settings.filters = [["allocated_to", "=", frappe.session.user]];
	settings.onload = function (listview) {
		onload?.(listview);
		// CSS also covers the asynchronously loaded/rebuilt saved-filter menu.
		if (frappe.session.user !== "Administrator") {
			$("<style>")
				.text(
					'.saved-filter-item[data-name^="todo-default-"] .remove-filter { display: none !important; }'
				)
				.appendTo(listview.page.wrapper);
		}
		// Existing user settings may contain an empty filter list. Prefill once,
		// while respecting an explicitly selected assignee or a linked route.
		if (
			!listview.filter_area.get().some((filter) => filter[1] === "allocated_to") &&
			!Object.prototype.hasOwnProperty.call(frappe.route_options || {}, "allocated_to")
		) {
			listview.filter_area.add([["ToDo", "allocated_to", "=", frappe.session.user]], false);
		}
		const setup_filters = listview.setup_list_filter_by.bind(listview);
		listview.setup_list_filter_by = async function () {
			await frappe.xcall("erpnext.utilities.todo.ensure_default_filters");
			return setup_filters();
		};
	};
})();
