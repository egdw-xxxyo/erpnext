frappe.provide("erpnext.todo_planner");

// Register a ToDo-only route without adding a view mode to every DocType.
frappe.router.list_views_route.planner = "Planner";
erpnext.todo_planner.switch_view = function (listview, view) {
	erpnext.todo_planner.pending_filters = {
		view,
		filters: JSON.parse(JSON.stringify(listview.filter_area.get())),
	};
	frappe.set_route("List", "ToDo", view);
};

frappe.views.PlannerView = class ToDoPlanner extends frappe.views.ListView {
	get view_name() {
		return "Planner";
	}

	check_permissions() {
		if (this.doctype !== "ToDo") frappe.throw(__("Not permitted"));
		super.check_permissions();
	}

	async setup_defaults() {
		await super.setup_defaults();
		this.view = "Planner";
		this.hide_sort_selector = true;
		this.mode = this.view_user_settings.mode === "month" ? "month" : "week";
		this.anchor = moment(frappe.datetime.now_date());
		this.include_closed = Boolean(this.view_user_settings.include_closed);
		this.sections = {};
	}

	get_menu_items() {
		return [];
	}

	set_actions_menu_items() {}
	set_result_height() {}
	setup_paging_area() {}

	setup_view_menu() {
		this.views_menu = this.page.add_custom_button_group(__("Planner"), "calendar");
		this.page.add_custom_menu_item(
			this.views_menu,
			__("List View"),
			() => {
				erpnext.todo_planner.switch_view(this, "List");
			},
			true,
			null,
			"list"
		);
	}

	setup_view() {
		this.$result.addClass("todo-planner");
		this.$result.on("click", "[data-nav]", (event) => {
			const direction = $(event.currentTarget).data("nav");
			this.anchor =
				direction === "today"
					? moment(frappe.datetime.now_date())
					: this.anchor.clone().add(Number(direction), this.mode);
			this.refresh();
		});
		this.$result.on("click", "[data-mode]", (event) => {
			this.mode = $(event.currentTarget).data("mode");
			this.refresh();
		});
		this.$result.on("change", "[data-completed]", (event) => {
			this.include_closed = event.currentTarget.checked;
			this.refresh();
		});
		this.$result.on("click", "[data-retry]", () => this.refresh());
		this.$result.on("click", "[data-more]", (event) => this.load_more(event));
		this.$result.on("click", "[data-task]", (event) => {
			if ($(event.target).closest("a, button").length) return;
			frappe.set_route("Form", "ToDo", $(event.currentTarget).data("task"));
		});
		this.$result.on("dragstart", "[data-task]", (event) => {
			if (!event.currentTarget.draggable) return event.preventDefault();
			event.originalEvent.dataTransfer.setData(
				"application/x-todo",
				$(event.currentTarget).data("task")
			);
			event.originalEvent.dataTransfer.effectAllowed = "move";
		});
		this.$result.on("dragover", "[data-day]", (event) => {
			if (
				this.can_write &&
				Array.from(event.originalEvent.dataTransfer.types).includes("application/x-todo")
			) {
				event.preventDefault();
				event.originalEvent.dataTransfer.dropEffect = "move";
			}
		});
		this.$result.on("drop", "[data-day]", (event) => {
			event.preventDefault();
			const name = event.originalEvent.dataTransfer.getData("application/x-todo");
			if (name && this.can_write) this.schedule(name, $(event.currentTarget).data("day"));
		});
		this.settings.onload?.(this);
		// Deadlines can pass without any document update arriving over realtime.
		this.deadline_timer = setInterval(() => {
			if (document.visibilityState === "visible" && frappe.get_route_str() === this.page_name) {
				this.refresh();
			}
		}, 60000);
	}

	get_range() {
		const start =
			this.mode === "week"
				? this.anchor.clone().startOf("isoWeek")
				: this.anchor.clone().startOf("month").startOf("isoWeek");
		const end =
			this.mode === "week"
				? start.clone().add(7, "days")
				: this.anchor.clone().endOf("month").endOf("isoWeek").add(1, "day").startOf("day");
		return { start, end };
	}

	async refresh() {
		if (!this.filter_area || !this.$result) return;
		const generation = (this.generation || 0) + 1;
		this.generation = generation;
		const { start, end } = this.get_range();
		this.query = {
			start: frappe.datetime.convert_to_system_tz(start.format("YYYY-MM-DD HH:mm:ss")),
			end: frappe.datetime.convert_to_system_tz(end.format("YYYY-MM-DD HH:mm:ss")),
			filters: this.filter_area.get(),
			include_closed: this.include_closed ? 1 : 0,
		};
		this.update_url_with_filters();
		this.save_view_user_settings({
			filters: this.query.filters,
			mode: this.mode,
			include_closed: this.include_closed,
		});
		this.$result.attr("aria-busy", "true");
		if (!this.$result.children().length) this.$result.text(__("Loading..."));
		try {
			const sections = ["calendar", "overdue", "unscheduled"];
			const responses = await Promise.all(
				sections.map((section) =>
					frappe.xcall("erpnext.utilities.todo_planner.get_tasks", { ...this.query, section })
				)
			);
			if (generation !== this.generation) return;
			sections.forEach((section, index) => {
				this.sections[section] = responses[index];
			});
			this.render_planner();
			this.setup_realtime_updates();
		} catch (error) {
			if (generation === this.generation) {
				this.$result.html(`<div class="tp-error">${__("Could not load tasks")}
					<button class="btn btn-default btn-sm" data-retry>${__("Retry")}</button></div>`);
			}
		} finally {
			if (generation === this.generation) this.$result.attr("aria-busy", "false");
		}
	}

	process_document_refreshes() {
		this.pending_document_refreshes = [];
		if (frappe.get_route_str() === this.page_name) this.refresh();
	}

	async load_more(event) {
		const button = $(event.currentTarget);
		const section = button.data("more");
		const generation = this.generation;
		button.prop("disabled", true);
		try {
			const result = await frappe.xcall("erpnext.utilities.todo_planner.get_tasks", {
				...this.query,
				section,
				offset: this.sections[section].tasks.length,
			});
			if (generation !== this.generation) return;
			this.sections[section].tasks.push(...result.tasks);
			this.sections[section].has_more = result.has_more;
			this.render_planner();
		} finally {
			button.prop("disabled", false);
		}
	}

	more_button(section) {
		return this.sections[section].has_more
			? `<button class="btn btn-default btn-sm tp-more"
			data-more="${section}">${__("Load More")}</button>`
			: "";
	}

	card(task) {
		const esc = frappe.utils.escape_html;
		const title = strip_html(task.description || "").trim() || task.name;
		const overdue = task.is_overdue;
		const deadline = task.deadline
			? frappe.datetime.convert_to_user_tz(task.deadline, false).format("DD.MM.YYYY · HH:mm")
			: "";
		const reference =
			task.reference_type && task.reference_name
				? `<div class="tp-reference">
			<span>${esc(__(task.reference_type))}</span>
			<a href="${esc(frappe.utils.get_form_link(task.reference_type, task.reference_name))}">${esc(
						task.reference_name
				  )} ↗</a></div>`
				: "";
		return `<article class="tp-card ${overdue ? "tp-overdue" : ""} ${
			task.status === "Closed" ? "tp-closed" : ""
		}"
			data-task="${esc(task.name)}" draggable="${this.can_write && task.status === "Open"}">
			<a class="tp-title" href="${esc(frappe.utils.get_form_link("ToDo", task.name))}" title="${esc(title)}">${esc(
			title
		)}</a>
			<div class="tp-badges"><span class="indicator-pill ${task.status === "Closed" ? "green" : "orange"}">${esc(
			__(task.status)
		)}</span>
			<span class="tp-priority">${esc(__(task.priority))}</span>
			${overdue ? `<span class="indicator-pill red">${__("Overdue", null, "ToDo")}</span>` : ""}</div>
			${
				deadline
					? `<div class="tp-deadline">${__("Deadline")}: <strong>${deadline}</strong></div>`
					: `<span class="indicator-pill gray">${__("No Deadline", null, "ToDo")}</span>`
			}
			<div class="tp-assigned">${__("Assignment Date")}: ${
			task.date ? esc(frappe.datetime.str_to_user(task.date)) : "—"
		}</div>
			${reference}
		</article>`;
	}

	render_planner() {
		const { start, end } = this.get_range();
		const dates = [];
		for (let date = start.clone(); date.isBefore(end); date.add(1, "day")) dates.push(date.clone());
		const grouped = {};
		this.sections.calendar.tasks.forEach((task) => {
			const day = frappe.datetime.convert_to_user_tz(task.deadline, false).format("YYYY-MM-DD");
			(grouped[day] ||= []).push(task);
		});
		const heading =
			this.mode === "month"
				? this.anchor.format("MMMM YYYY")
				: `${start.format("DD.MM.YYYY")} – ${end.clone().subtract(1, "day").format("DD.MM.YYYY")}`;
		const weekdays = [
			__("Monday"),
			__("Tuesday"),
			__("Wednesday"),
			__("Thursday"),
			__("Friday"),
			__("Saturday"),
			__("Sunday"),
		];
		const count = (section) =>
			`${this.sections[section].tasks.length}${this.sections[section].has_more ? "+" : ""}`;
		this.$result.html(`<div class="tp-toolbar">
			<div class="tp-navigation"><button class="btn btn-default btn-sm" data-nav="-1" aria-label="${__(
				"Previous"
			)}">‹</button>
			<button class="btn btn-default btn-sm" data-nav="today">${__("Today")}</button>
			<button class="btn btn-default btn-sm" data-nav="1" aria-label="${__(
				"Next"
			)}">›</button><strong>${heading}</strong></div>
			<div class="tp-options"><label><input type="checkbox" data-completed ${
				this.include_closed ? "checked" : ""
			}> ${__("Show Completed Tasks")}</label>
			<div class="btn-group"><button class="btn btn-sm ${
				this.mode === "week" ? "btn-primary" : "btn-default"
			}" data-mode="week" aria-pressed="${this.mode === "week"}">${__("Week")}</button>
			<button class="btn btn-sm ${
				this.mode === "month" ? "btn-primary" : "btn-default"
			}" data-mode="month" aria-pressed="${this.mode === "month"}">${__("Month")}</button></div></div>
		</div>
		<details class="tp-overdue-section" ${this.sections.overdue.tasks.length ? "open" : ""}>
			<summary>${__("Overdue ToDo Tasks")} <span class="tp-count">${count("overdue")}</span></summary>
			<div class="tp-overdue-cards">${
				this.sections.overdue.tasks.map((task) => this.card(task)).join("") ||
				`<p class="text-muted">${__("No overdue tasks")}</p>`
			}</div>${this.more_button("overdue")}
		</details>
		<div class="tp-layout"><div class="tp-calendar-wrap"><div class="tp-calendar tp-${this.mode}">
			${weekdays.map((day) => `<div class="tp-weekday">${day}</div>`).join("")}
			${dates
				.map((date) => {
					const key = date.format("YYYY-MM-DD");
					return `<section class="tp-day ${key === frappe.datetime.now_date() ? "tp-today" : ""} ${
						this.mode === "month" && date.month() !== this.anchor.month() ? "tp-outside" : ""
					}" data-day="${key}">
					<div class="tp-day-label"><time datetime="${key}">${date.format(
						this.mode === "week" ? "DD.MM" : "D"
					)}</time><span>${(grouped[key] || []).length || ""}</span></div>
					<div class="tp-day-cards" tabindex="0" aria-label="${key}">${(grouped[key] || [])
						.map((task) => this.card(task))
						.join("")}</div>
				</section>`;
				})
				.join("")}</div>${this.more_button("calendar")}</div>
		<aside class="tp-backlog"><h3>${__("Tasks Without Deadlines")} <span class="tp-count">${count(
			"unscheduled"
		)}</span></h3>
			<p class="text-muted tp-hint">${__("Set a deadline or drag a task to a day")}</p>
			<div class="tp-backlog-cards">${
				this.sections.unscheduled.tasks.map((task) => this.card(task)).join("") ||
				`<p class="text-muted">${__("No tasks without deadlines")}</p>`
			}</div>
			${this.more_button("unscheduled")}</aside></div>`);
	}

	schedule(name, day) {
		const task = Object.values(this.sections)
			.flatMap((section) => section.tasks)
			.find((task) => task.name === name);
		if (!task || task.status !== "Open") return;
		const time = task.deadline
			? frappe.datetime.convert_to_user_tz(task.deadline, false).format("HH:mm:ss")
			: "18:00:00";
		const dialog = new frappe.ui.Dialog({
			title: __("Set Deadline"),
			fields: [
				{
					fieldname: "deadline",
					fieldtype: "Datetime",
					label: __("Deadline"),
					reqd: 1,
					default: day ? frappe.datetime.convert_to_system_tz(`${day} ${time}`) : task.deadline,
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				dialog.disable_primary_action();
				try {
					await frappe.db.set_value("ToDo", name, "deadline", values.deadline);
					dialog.hide();
					this.refresh();
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}
};
