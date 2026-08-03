frappe.listview_settings["Task"] = {
	add_fields: [
		"project",
		"status",
		"priority",
		"exp_start_date",
		"exp_end_date",
		"subject",
		"progress",
		"depends_on_tasks",
	],
	filters: [["status", "not in", ["Completed", "Cancelled"]]],
	onload: function (listview) {
		var method = "erpnext.projects.doctype.task.task.set_multiple_status";

		listview.page.add_menu_item(__("Set as New"), function () {
			listview.call_for_selected_items(method, { status: "New" });
		});

		listview.page.add_menu_item(__("Set as Completed"), function () {
			listview.call_for_selected_items(method, { status: "Completed" });
		});
	},
	get_indicator: function (doc) {
		var colors = {
			New: "grey",
			"In Progress": "blue",
			"Awaiting Info": "yellow",
			Blocked: "red",
			"In Review": "purple",
			Completed: "green",
			Cancelled: "dark grey",
		};

		if (
			doc.exp_end_date &&
			!["Completed", "Cancelled"].includes(doc.status) &&
			frappe.datetime.get_diff(doc.exp_end_date, frappe.datetime.get_today()) < 0
		) {
			return [
				__("Overdue") + " (" + __(doc.status) + ")",
				"red",
				"exp_end_date,<,Today",
			];
		}

		return [__(doc.status), colors[doc.status], "status,=," + doc.status];
	},
	gantt_custom_popup_html: function (ganttobj, task) {
		let html = `
			<a class="text-white mb-2 inline-block cursor-pointer"
				href="/app/task/${ganttobj.id}"">
				${ganttobj.name}
			</a>
		`;

		if (task.project) {
			html += `<p class="mb-1">${__("Project")}:
				<a class="text-white inline-block"
					href="/app/project/${task.project}"">
					${task.project}
				</a>
			</p>`;
		}
		html += `<p class="mb-1">
			${__("Progress")}:
			<span class="text-white">${ganttobj.progress}%</span>
		</p>`;

		if (task._assign) {
			const assign_list = JSON.parse(task._assign);
			const assignment_wrapper = `
				<span>Assigned to:</span>
				<span class="text-white">
					${assign_list.map((user) => frappe.user_info(user).fullname).join(", ")}
				</span>
			`;
			html += assignment_wrapper;
		}

		return `<div class="p-3" style="min-width: 220px">${html}</div>`;
	},
};
