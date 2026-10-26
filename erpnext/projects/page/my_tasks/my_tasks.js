frappe.pages["my-tasks"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("My Tasks"),
		single_column: true,
	});
	wrapper.my_tasks = new MyTasks(page);
	// Sidebar links only change ?view= on an already open page, which fires no page show.
	frappe.router.on("change", () => {
		if (frappe.get_route()[0] === "my-tasks") wrapper.my_tasks.show();
	});
};

frappe.pages["my-tasks"].on_page_show = function (wrapper) {
	wrapper.my_tasks?.show();
};

const MT_TABS = [
	["today", "fa fa-sun-o", "Today"],
	["overdue", "fa fa-exclamation-circle", "Overdue"],
	["upcoming", "fa fa-calendar", "Upcoming"],
	["all", "fa fa-list", "All Mine"],
];
const MT_PRIORITY = { High: "red", Medium: "orange", Low: "gray" };

class MyTasks {
	constructor(page) {
		this.page = page;
		this.view = "today";
		this.tasks = [];
		this.counts = {};
		this.include_closed = false;
		this.make();
	}

	make() {
		this.page.set_primary_action(__("New Reminder"), () => this.open_dialog(), "add");
		this.page.add_inner_button(__("Planner"), () => frappe.set_route("List", "ToDo", "Planner"));
		this.page.main.html(`
			<div class="my-tasks">
				<div class="mt-tabs" role="tablist"></div>
				<form class="mt-add">
					<input class="form-control mt-add-text" maxlength="500"
						placeholder="${__("Add a task and press Enter")}">
					<input class="form-control mt-add-deadline" type="datetime-local"
						title="${__("Deadline")}">
					<button type="submit" class="btn btn-primary btn-sm">${__("Add")}</button>
					<button type="button" class="btn btn-default btn-sm mt-more-btn">
						${__("More")}</button>
				</form>
				<label class="mt-closed">
					<input type="checkbox"> ${__("Show completed")}
				</label>
				<div class="mt-list"></div>
			</div>
		`);
		this.$root = this.page.main.find(".my-tasks");
		this.$list = this.$root.find(".mt-list");
		this.$root.find(".mt-add").on("submit", (e) => {
			e.preventDefault();
			this.quick_add();
		});
		this.$root.find(".mt-more-btn").on("click", () =>
			this.open_dialog({
				description: this.$root.find(".mt-add-text").val(),
				deadline: this.input_deadline(),
			})
		);
		this.$root.find(".mt-closed input").on("change", (e) => {
			this.include_closed = e.currentTarget.checked;
			this.refresh();
		});
		this.$root.on("click", "[data-tab]", (e) => this.set_view($(e.currentTarget).data("tab")));
		this.$root.on("change", "[data-done]", (e) => this.toggle(e.currentTarget));
		this.$root.on("click", "[data-more]", () => this.refresh(true));
		this.$root.on("click", "[data-task]", (e) => {
			if ($(e.target).closest("a[href], input, button").length) return;
			frappe.set_route("Form", "ToDo", $(e.currentTarget).data("task"));
		});
		frappe.realtime.doctype_subscribe("ToDo");
		frappe.realtime.on("list_update", (data) => {
			if (data?.doctype === "ToDo" && frappe.get_route_str() === "my-tasks") {
				this.schedule_refresh();
			}
		});
	}

	show() {
		const view = frappe.route_options?.view || new URLSearchParams(window.location.search).get("view");
		frappe.route_options = null;
		if (MT_TABS.some(([key]) => key === view)) this.view = view;
		this.refresh();
	}

	set_view(view) {
		this.view = view;
		this.refresh();
	}

	schedule_refresh() {
		clearTimeout(this.refresh_timer);
		this.refresh_timer = setTimeout(() => this.refresh(), 500);
	}

	async refresh(more = false) {
		const generation = (this.generation || 0) + 1;
		this.generation = generation;
		this.render_tabs();
		if (!more && !this.tasks.length) this.$list.html(this.message(__("Loading...")));
		try {
			const r = await frappe.xcall("erpnext.projects.page.my_tasks.my_tasks.get_tasks", {
				view: this.view,
				include_closed: this.include_closed ? 1 : 0,
				start: more ? this.tasks.length : 0,
			});
			if (generation !== this.generation) return;
			this.tasks = more ? [...this.tasks, ...r.tasks] : r.tasks;
			this.has_more = r.has_more;
			this.counts = r.counts;
			this.render_tabs();
			this.render_list();
		} catch (e) {
			if (generation === this.generation) {
				this.$list.html(this.message(__("Could not load tasks")));
			}
		}
	}

	render_tabs() {
		this.$root.find(".mt-tabs").html(
			MT_TABS.map(([key, icon, label]) => {
				const count = this.counts[key];
				const badge =
					count == null
						? ""
						: `<span class="mt-count ${
								key === "overdue" && count ? "mt-count-alert" : ""
						  }">${count}</span>`;
				return `<button class="mt-tab ${key === this.view ? "active" : ""}" role="tab"
					data-tab="${key}"><i class="${icon}"></i> ${__(label)} ${badge}</button>`;
			}).join("")
		);
		this.$root.find(".mt-closed").toggle(this.view !== "overdue");
	}

	render_list() {
		if (!this.tasks.length) {
			this.$list.html(this.message(__("Nothing here")));
			return;
		}
		const more = this.has_more
			? `<button class="btn btn-default btn-sm mt-load-more" data-more>${__("Load More")}</button>`
			: "";
		this.$list.html(this.tasks.map((t) => this.row(t)).join("") + more);
	}

	row(t) {
		const esc = frappe.utils.escape_html;
		const title = strip_html(t.description || "").trim() || t.name;
		const closed = t.status === "Closed";
		const when = (value) => frappe.format(value, { fieldtype: "Datetime" });
		const meta = [];
		if (t.deadline) {
			meta.push(`<span class="mt-deadline ${t.is_overdue ? "mt-overdue" : ""}">
				<i class="fa fa-clock-o"></i> ${when(t.deadline)}</span>`);
		}
		if (t.remind_at) {
			meta.push(`<span title="${__("Remind At")}"><i class="fa fa-bell-o"></i>
				${when(t.remind_at)}</span>`);
		}
		if (t.reference_type && t.reference_name) {
			const href = frappe.utils.get_form_link(t.reference_type, t.reference_name);
			meta.push(`<a href="${href}"><i class="fa fa-link"></i>
				${esc(__(t.reference_type))}: ${esc(t.reference_name)}</a>`);
		}
		if (t.assigned_by && t.assigned_by !== frappe.session.user) {
			meta.push(`<span>${__("From")} ${erpnext.entity.user(t.assigned_by, { size: 16 })}</span>`);
		}
		const priority = t.priority || "Low";
		return `<div class="mt-row ${closed ? "mt-done" : ""}" data-task="${esc(t.name)}">
			<input type="checkbox" class="mt-check" data-done="${esc(t.name)}"
				${closed ? "checked" : ""} title="${__("Mark as done")}">
			<div class="mt-body">
				<div class="mt-title">${esc(title)}</div>
				<div class="mt-meta">${meta.join("")}</div>
			</div>
			<span class="indicator-pill ${MT_PRIORITY[priority] || "gray"}">${__(priority)}</span>
		</div>`;
	}

	message(text) {
		return `<div class="mt-empty">${text}</div>`;
	}

	input_deadline() {
		const value = this.$root.find(".mt-add-deadline").val();
		return value
			? frappe.datetime.convert_to_system_tz(moment(value).format("YYYY-MM-DD HH:mm:ss"))
			: null;
	}

	async quick_add() {
		const $text = this.$root.find(".mt-add-text");
		const description = ($text.val() || "").trim();
		if (!description) return;
		await this.create({ description, deadline: this.input_deadline() });
		$text.val("");
		this.$root.find(".mt-add-deadline").val("");
	}

	async create(values) {
		await frappe.xcall("erpnext.projects.page.my_tasks.my_tasks.quick_add", values);
		frappe.show_alert({ message: __("Task added"), indicator: "green" });
		this.refresh();
	}

	open_dialog(defaults = {}) {
		const dialog = new frappe.ui.Dialog({
			title: __("New Reminder"),
			fields: [
				{ fieldname: "description", fieldtype: "Small Text", label: __("Task"), reqd: 1 },
				{ fieldname: "deadline", fieldtype: "Datetime", label: __("Deadline") },
				{ fieldname: "remind_at", fieldtype: "Datetime", label: __("Remind At") },
				{
					fieldname: "priority",
					fieldtype: "Select",
					label: __("Priority"),
					options: [
						{ value: "Low", label: __("Low") },
						{ value: "Medium", label: __("Medium") },
						{ value: "High", label: __("High") },
					],
					default: "Low",
				},
				{ fieldtype: "Section Break", label: __("Link to Document"), collapsible: 1 },
				{
					fieldname: "reference_type",
					fieldtype: "Link",
					options: "DocType",
					label: __("Document Type"),
					get_query: () => ({ filters: { istable: 0, issingle: 0 } }),
				},
				{
					fieldname: "reference_name",
					fieldtype: "Dynamic Link",
					options: "reference_type",
					label: __("Document"),
					depends_on: "reference_type",
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await this.create(values);
				dialog.hide();
				this.$root.find(".mt-add-text, .mt-add-deadline").val("");
			},
		});
		dialog.set_values(defaults);
		dialog.show();
	}

	async toggle(input) {
		const status = input.checked ? "Closed" : "Open";
		$(input).closest(".mt-row").toggleClass("mt-done", input.checked);
		try {
			this.counts = await frappe.xcall("erpnext.projects.page.my_tasks.my_tasks.set_status", {
				name: $(input).data("done"),
				status,
			});
			this.render_tabs();
			if (!this.include_closed || this.view === "overdue") this.schedule_refresh();
		} catch (e) {
			input.checked = !input.checked;
			$(input).closest(".mt-row").toggleClass("mt-done", input.checked);
		}
	}
}
