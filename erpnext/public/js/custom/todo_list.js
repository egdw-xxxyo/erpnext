// Extend Frappe's ToDo list without replacing its reference-document action.
(() => {
	const settings = frappe.listview_settings["ToDo"];
	const onload = settings.onload;
	const refresh = settings.refresh;
	settings.refresh = function (listview) {
		refresh?.(listview);
		if (listview.views_list && !listview.views_menu.find('[data-view="Planner"]').length) {
			listview.views_list.icon_map.Planner = "calendar";
			listview.views_list.add_view_to_menu("Planner", () =>
				erpnext.todo_planner.switch_view(listview, "Planner")
			);
		}
	};
	settings.filters = [["allocated_to", "=", frappe.session.user]];
	settings.add_fields = [...(settings.add_fields || []), "deadline"];
	settings.formatters = {
		...settings.formatters,
		deadline(value, df) {
			if (!value) {
				return `<span class="indicator-pill gray">${__("No Deadline", null, "ToDo")}</span>`;
			}
			return frappe.format(value, df);
		},
	};
	settings.onload = function (listview) {
		onload?.(listview);
		const before_refresh = listview.before_refresh.bind(listview);
		listview.before_refresh = async function () {
			await before_refresh();
			const pending = erpnext.todo_planner.pending_filters;
			if (pending?.view === listview.view_name) {
				erpnext.todo_planner.pending_filters = null;
				await listview.filter_area.clear(false);
				await listview.filter_area.add(pending.filters, false);
			}
		};
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
