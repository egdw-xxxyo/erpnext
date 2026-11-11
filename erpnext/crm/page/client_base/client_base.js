const CB_API = "erpnext.crm.client_base";

frappe.pages["client-base"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Client Base"), single_column: true });
	wrapper.cb = new ClientBase(page);
};

frappe.pages["client-base"].on_page_show = function (wrapper) {
	if (wrapper.cb) wrapper.cb.load();
};

class ClientBase {
	constructor(page) {
		this.page = page;
		this.E = erpnext.entity;
		this.work_mode = 0;
		this.data = { rows: [], processed: 0, total: 0 };
		this.selected = new Set();
		this.open_hidden = new Set();
		this.expanded = new Set();
		this.editing = null;
		this.sort = null;
		this.dup_key = null;
		this.page.main.html(`<div class="client-base">
			<div class="cb-toolbar"></div>
			<div class="cb-scroll"></div>
			<div class="cb-bottom"></div></div>`);
		this.$root = this.page.main.find(".client-base");
		this.$toolbar = this.$root.find(".cb-toolbar");
		this.$body = this.$root.find(".cb-scroll");
		this.$bottom = this.$root.find(".cb-bottom");
		this.columns = [
			{ key: "contact", label: __("Contact"), val: (r) => (r.full_name || r.contact).toLowerCase() },
			{ key: "phone", label: __("Phone"), val: (r) => r.display_phone || "" },
			{ key: "designation", label: __("Position"), val: (r) => (r.designation || "").toLowerCase() },
			{
				key: "last_result",
				label: __("Last Result"),
				val: (r) => (r.last_result ? r.last_result.result_date : ""),
			},
			{
				key: "next_action",
				label: __("Next Action"),
				val: (r) => (r.next_action && r.next_action.date) || "9999",
			},
			{ key: "comment", label: __("Comment"), val: (r) => (r.cb_comment || "").toLowerCase() },
		];
		this.make_toolbar();
		this.bind();
		$(window).on(
			"resize.client-base",
			frappe.utils.debounce(() => this.fit(), 100)
		);
	}

	esc(v) {
		return frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));
	}

	plain(html) {
		return $("<div>")
			.html(html || "")
			.text();
	}

	dt(v) {
		return v ? frappe.datetime.str_to_user(v) : "";
	}

	make_toolbar() {
		const reload = () => this.load();
		const mk = (df) => {
			const $w = $('<div class="cb-field"></div>').appendTo(this.$toolbar);
			const c = frappe.ui.form.make_control({ df, parent: $w, render_input: true });
			c.refresh();
			return c;
		};
		this.f = {
			search: mk({ fieldtype: "Data", fieldname: "search", placeholder: __("Search"), change: reload }),
			military_unit: mk({
				fieldtype: "Link",
				options: "Military Unit",
				fieldname: "military_unit",
				placeholder: __("Military Unit"),
				change: reload,
			}),
			result: mk({
				fieldtype: "Link",
				options: "Call Result",
				fieldname: "result",
				placeholder: __("Last Result"),
				change: reload,
			}),
			favorite: mk({
				fieldtype: "Check",
				fieldname: "favorite",
				label: __("Favorites"),
				change: reload,
			}),
			only_due: mk({ fieldtype: "Check", fieldname: "only_due", label: __("Urgent"), change: reload }),
			show_hidden: mk({
				fieldtype: "Check",
				fieldname: "show_hidden",
				label: __("Show Hidden"),
				change: () => this.render(),
			}),
		};
		this.$reset = $(
			`<button class="btn btn-default btn-sm" style="display:none">
				<i class="fa fa-times"></i> ${__("Reset contact filter")}</button>`
		).appendTo(this.$toolbar);
		this.$counter = $('<div class="cb-counter"></div>').appendTo(this.$toolbar);
		this.$reset.on("click", () => {
			this.dup_key = null;
			this.load();
		});
	}

	filters() {
		const g = (k) => this.f[k].get_value();
		return {
			search: g("search"),
			military_unit: g("military_unit"),
			result: g("result"),
			favorite: g("favorite") ? 1 : 0,
			only_due: g("only_due") ? 1 : 0,
			dup_key: this.dup_key,
		};
	}

	load() {
		return frappe
			.call({
				method: `${CB_API}.get_rows`,
				args: { filters: this.filters(), work_mode: this.work_mode },
			})
			.then((r) => {
				this.data = r.message;
				const present = new Set(this.data.rows.map((x) => x.contact));
				this.selected = new Set([...this.selected].filter((c) => present.has(c)));
				this.render();
			});
	}

	call(method, args, freeze = true) {
		return frappe.call({ method: `${CB_API}.${method}`, args, freeze });
	}

	compare(a, b) {
		if (this.sort) {
			const col = this.columns.find((c) => c.key === this.sort.key);
			const x = col.val(a);
			const y = col.val(b);
			if (x !== y) return (x < y ? -1 : 1) * this.sort.dir;
		}
		if (a.urgency !== b.urgency) return b.urgency - a.urgency;
		if (a.cb_favorite !== b.cb_favorite) return b.cb_favorite - a.cb_favorite;
		return (a.full_name || a.contact).localeCompare(b.full_name || b.contact);
	}

	groups() {
		const show_all = this.work_mode || this.f.show_hidden.get_value();
		const map = new Map();
		this.data.rows.forEach((r) => {
			if (!map.has(r.unit))
				map.set(r.unit, { unit: r.unit, unit_name: r.unit_name, rows: [], hidden: 0 });
			const g = map.get(r.unit);
			if (r.cb_hidden && !this.work_mode) g.hidden += 1;
			if (!r.cb_hidden || show_all || this.open_hidden.has(r.unit)) g.rows.push(r);
		});
		const list = [...map.values()].filter((g) => g.rows.length || g.hidden);
		list.forEach((g) => {
			g.rows.sort((a, b) => this.compare(a, b));
			g.urgency = Math.max(0, ...g.rows.filter((r) => !r.cb_hidden).map((r) => r.urgency));
		});
		list.sort((a, b) => b.urgency - a.urgency || String(a.unit).localeCompare(String(b.unit)));
		return list;
	}

	render() {
		this.$reset.toggle(!!this.dup_key);
		this.$counter.text(
			`${this.work_mode ? __("Worked") : __("Processed contacts")}: ${this.data.processed}/${
				this.data.total
			}`
		);
		this.$toolbar.find(".cb-field").toggle(!this.work_mode);

		const groups = this.groups();
		if (!groups.length) {
			this.$body.html(
				`<div class="cb-empty">${
					this.work_mode ? __("No contacts in work") : __("No contacts")
				}</div>`
			);
			this.render_bottom();
			return;
		}

		const arrow = (key) =>
			this.sort && this.sort.key === key
				? `<i class="fa fa-sort-${this.sort.dir > 0 ? "asc" : "desc"}"></i>`
				: `<i class="fa fa-sort text-muted"></i>`;
		const ncols = this.columns.length + 2;
		let html = `<table class="cb-table"><thead><tr>
			<th class="cb-check">${this.work_mode ? "" : '<input type="checkbox" class="cb-all">'}</th>
			${this.columns
				.map(
					(c) =>
						`<th class="cb-sortable cb-col-${c.key}" data-key="${c.key}">${c.label} ${arrow(
							c.key
						)}</th>`
				)
				.join("")}
			<th></th></tr></thead><tbody>`;
		groups.forEach((g) => {
			const hidden_note = g.hidden
				? `<span class="cb-hidden-note">${__("{0} hidden", [g.hidden])}
					<button class="btn btn-xs btn-default cb-toggle-hidden" data-unit="${this.esc(g.unit)}">${
						this.open_hidden.has(g.unit) ? __("Hide") : __("Show")
				  }</button></span>`
				: "";
			html += `<tr class="cb-group"><td colspan="${ncols}"><div class="cb-group-line">
				${this.E.military_unit({ name: g.unit, sub: g.unit_name || __("Military Unit") }, { card: true, size: 36 })}
				<span class="cb-group-count">${
					g.rows.filter((r) => !r.cb_hidden).length
				}</span>${hidden_note}</div></td></tr>`;
			g.rows.forEach((r) => (html += this.row_html(r)));
		});
		html += "</tbody></table>";
		this.$body.html(html);
		this.render_bottom();
	}

	row_class(r) {
		const cls = [];
		if (this.work_mode && r.cb_done) cls.push("cb-done");
		else if (r.urgency === 2) cls.push("cb-overdue");
		else if (r.urgency === 1) cls.push("cb-today");
		if (r.cb_hidden && !this.work_mode) cls.push("cb-is-hidden");
		return cls.join(" ");
	}

	row_html(r) {
		const dup = r.dup_count
			? `<a class="cb-dup" data-key="${this.esc(r.dup_key)}">(${r.dup_count})</a>`
			: "";
		const contact = this.E.contact(
			{
				contact: r.contact,
				full_name: r.full_name || r.contact,
				image: r.image,
				sub: r.call_sign ? `«${r.call_sign}»` : r.designation || r.display_phone || "",
			},
			{ card: true, size: 36 }
		);
		const phone = r.display_phone
			? `<a href="tel:${this.esc(r.display_phone.replace(/[^\d+]/g, ""))}">${this.esc(
					r.display_phone
			  )}</a>`
			: "";
		const lr = r.last_result
			? `<a class="cb-history" href="#">${this.esc(__(r.last_result.result))}</a>
				<div class="cb-sub">${this.dt(r.last_result.result_date)}</div>`
			: "";
		const na = r.next_action
			? `<a class="cb-next" href="#">${
					this.esc(this.plain(r.next_action.description)) || __("Task")
			  }</a>
				<div class="cb-sub">${this.dt(r.next_action.date)}${
					r.open_todos > 1 ? ` · ${__("{0} open", [r.open_todos])}` : ""
			  }</div>`
			: "";
		const check = this.work_mode
			? ""
			: `<input type="checkbox" class="cb-sel" ${this.selected.has(r.contact) ? "checked" : ""}>`;
		const actions = this.work_mode
			? `<button class="btn btn-xs btn-default cb-result">${__("Add Result")}</button>
				<button class="btn btn-xs ${r.cb_done ? "btn-success" : "btn-primary"} cb-finish">${
					r.cb_done ? __("Finished") : __("Finish")
			  }</button>`
			: `<button class="btn btn-xs btn-default cb-result">${__("Add Result")}</button>
				<i class="fa fa-star cb-icon cb-fav ${r.cb_favorite ? "active" : ""}" title="${__("Favorite")}"></i>
				<i class="fa ${r.cb_hidden ? "fa-eye" : "fa-eye-slash"} cb-icon cb-hide" title="${
					r.cb_hidden ? __("Unhide") : __("Hide")
			  }"></i>`;
		return `<tr class="cb-row ${this.row_class(r)}" data-contact="${this.esc(
			r.contact
		)}" data-unit="${this.esc(r.unit)}">
			<td class="cb-check">${check}</td>
			<td class="cb-col-contact">${contact}${dup}</td>
			<td class="cb-col-phone">${phone}</td>
			<td class="cb-col-designation">${this.esc(r.designation)}</td>
			<td class="cb-col-last_result">${lr}</td>
			<td class="cb-col-next_action">${na}</td>
			<td class="cb-col-comment">${this.comment_html(r)}</td>
			<td class="cb-actions">${actions}
				<i class="fa fa-history cb-icon cb-history" title="${__("History")}"></i></td></tr>`;
	}

	comment_html(r) {
		if (this.editing === r.contact) {
			return `<textarea class="form-control cb-comment-input" rows="3">${this.esc(
				r.cb_comment
			)}</textarea>
				<div class="cb-comment-btns">
					<button class="btn btn-xs btn-primary cb-comment-save">${__("Save")}</button>
					<button class="btn btn-xs btn-default cb-comment-cancel">${__("Cancel")}</button></div>`;
		}
		const open = this.expanded.has(r.contact) ? "expanded" : "";
		const text = r.cb_comment
			? `<div class="cb-comment-text ${open}" title="${__("Click to expand")}">${this.esc(
					r.cb_comment
			  )}</div>`
			: "";
		return `<div class="cb-comment">${text}<i class="fa fa-pencil cb-icon cb-comment-edit" title="${__(
			"Edit"
		)}"></i></div>`;
	}

	fit() {
		const el = this.$body.get(0);
		if (!el || !el.offsetParent) return;
		const bottom = this.$bottom.outerHeight() || 0;
		const height = window.innerHeight - el.getBoundingClientRect().top - bottom - 16;
		this.$body.css("max-height", `${Math.max(240, height)}px`);
	}

	render_bottom() {
		if (this.work_mode) {
			this.$bottom.html(`<button class="btn btn-danger cb-finish-work">${__("Finish Work")}</button>`);
		} else if (this.selected.size) {
			this.$bottom.html(
				`<button class="btn btn-primary cb-start">${__("Start Work")} (${
					this.selected.size
				})</button>`
			);
		} else {
			this.$bottom.empty();
		}
		this.fit();
	}

	row_of(el) {
		const $tr = $(el).closest("tr.cb-row");
		const contact = $tr.attr("data-contact");
		const unit = $tr.attr("data-unit");
		return this.data.rows.find((r) => r.contact === contact && r.unit === unit);
	}

	bind() {
		const root = this.$root;
		root.on("click", ".cb-sortable", (e) => {
			const key = $(e.currentTarget).attr("data-key");
			if (!this.sort || this.sort.key !== key) this.sort = { key, dir: 1 };
			else if (this.sort.dir === 1) this.sort.dir = -1;
			else this.sort = null;
			this.render();
		});
		root.on("click", ".cb-toggle-hidden", (e) => {
			const unit = $(e.currentTarget).attr("data-unit");
			this.open_hidden.has(unit) ? this.open_hidden.delete(unit) : this.open_hidden.add(unit);
			this.render();
		});
		root.on("click", ".cb-dup", (e) => {
			e.preventDefault();
			this.dup_key = $(e.currentTarget).attr("data-key");
			this.load();
		});
		root.on("change", ".cb-sel", (e) => {
			const r = this.row_of(e.currentTarget);
			e.currentTarget.checked ? this.selected.add(r.contact) : this.selected.delete(r.contact);
			this.render_bottom();
		});
		root.on("change", ".cb-all", (e) => {
			const on = e.currentTarget.checked;
			this.groups().forEach((g) =>
				g.rows.forEach((r) => (on ? this.selected.add(r.contact) : this.selected.delete(r.contact)))
			);
			this.render();
		});
		root.on("click", ".cb-fav", (e) => this.toggle_flag(e, "cb_favorite"));
		root.on("click", ".cb-hide", (e) => this.toggle_flag(e, "cb_hidden"));
		root.on("click", ".cb-result", (e) => this.result_dialog(this.row_of(e.currentTarget)));
		root.on("click", ".cb-history", (e) => {
			e.preventDefault();
			this.history_dialog(this.row_of(e.currentTarget));
		});
		root.on("click", ".cb-next", (e) => {
			e.preventDefault();
			this.next_dialog(this.row_of(e.currentTarget));
		});
		root.on("click", ".cb-finish", (e) => this.finish_dialog(this.row_of(e.currentTarget).contact));
		root.on("click", ".cb-start", () => this.start_work());
		root.on("click", ".cb-finish-work", () => this.finish_work());
		root.on("click", ".cb-comment-text", (e) => {
			const r = this.row_of(e.currentTarget);
			this.expanded.has(r.contact) ? this.expanded.delete(r.contact) : this.expanded.add(r.contact);
			$(e.currentTarget).toggleClass("expanded");
		});
		root.on("click", ".cb-comment-edit", (e) => {
			this.editing = this.row_of(e.currentTarget).contact;
			this.render();
			this.$body.find(".cb-comment-input").trigger("focus");
		});
		root.on("click", ".cb-comment-cancel", () => {
			this.editing = null;
			this.render();
		});
		root.on("click", ".cb-comment-save", (e) => {
			const r = this.row_of(e.currentTarget);
			const comment = $(e.currentTarget).closest("td").find(".cb-comment-input").val();
			this.call("set_comment", { contact: r.contact, comment }, false).then(() => {
				this.data.rows
					.filter((x) => x.contact === r.contact)
					.forEach((x) => (x.cb_comment = comment));
				this.editing = null;
				this.render();
			});
		});
	}

	toggle_flag(e, field) {
		const r = this.row_of(e.currentTarget);
		this.call("set_flag", { contact: r.contact, field, value: r[field] ? 0 : 1 }, false).then(() =>
			this.load()
		);
	}

	start_work() {
		this.call("start_work", { contacts: [...this.selected] }).then(() => {
			this.selected.clear();
			this.work_mode = 1;
			this.sort = null;
			this.load();
		});
	}

	finish_work() {
		frappe.confirm(__("Finish work? All contacts will no longer be marked as in work."), () => {
			this.call("finish_work").then(() => {
				this.work_mode = 0;
				this.load();
			});
		});
	}

	contact_header(r) {
		return `<div class="cb-dialog-head">
			${this.E.contact(
				{
					contact: r.contact,
					full_name: r.full_name || r.contact,
					image: r.image,
					sub: r.call_sign ? `«${r.call_sign}»` : "",
				},
				{ card: true }
			)}
			${this.E.military_unit({ name: r.unit, sub: r.unit_name || __("Military Unit") }, { card: true })}
			<div class="cb-sub">${this.esc(r.display_phone)} ${r.designation ? "· " + this.esc(r.designation) : ""}</div>
		</div>`;
	}

	todo_link(t) {
		return this.E.doc_link({ doctype: "ToDo", name: t.name, label: this.plain(t.description) || t.name });
	}

	result_dialog(r) {
		const d = new frappe.ui.Dialog({
			title: __("Add Result"),
			fields: [
				{ fieldtype: "HTML", fieldname: "info", options: this.contact_header(r) },
				{
					fieldtype: "Link",
					fieldname: "result",
					label: __("Result"),
					options: "Call Result",
					reqd: 1,
				},
				{
					fieldtype: "Datetime",
					fieldname: "result_date",
					label: __("Date"),
					default: frappe.datetime.now_datetime(),
					reqd: 1,
				},
				{ fieldtype: "Small Text", fieldname: "comment", label: __("Comment") },
				{ fieldtype: "Section Break", label: __("Next Action") },
				{ fieldtype: "Small Text", fieldname: "next_description", label: __("Description") },
				{ fieldtype: "Date", fieldname: "next_date", label: __("Due Date") },
				{
					fieldtype: "Link",
					fieldname: "next_user",
					label: __("Assign To"),
					options: "User",
					default: frappe.session.user,
				},
			],
			primary_action_label: __("Save"),
			primary_action: (v) => {
				this.call("add_result", { contact: r.contact, unit: r.unit, ...v }).then(() => {
					d.hide();
					this.load();
				});
			},
		});
		d.show();
	}

	next_dialog(r) {
		this.call("get_history", { contact: r.contact }, false).then((res) => {
			const open = res.message.todos.filter((t) => t.status === "Open");
			const next = open.find((t) => t.name === r.next_action.name) || r.next_action;
			const others = open.filter((t) => t.name !== next.name);
			const row = (label, value) => `<tr><th>${label}</th><td>${value || "—"}</td></tr>`;
			const d = new frappe.ui.Dialog({
				title: __("Next Action"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "body",
						options: `${this.contact_header(r)}
							<table class="table table-sm cb-info">
								${row(__("Task"), this.todo_link(next))}
								${row(__("Due Date"), this.dt(next.date))}
								${row(__("Priority"), next.priority ? __(next.priority) : "")}
								${row(__("Assigned To"), next.allocated_to ? this.E.user(next.allocated_to, { size: 20 }) : "")}
								${row(__("Description"), `<div class="cb-desc">${next.description || ""}</div>`)}
							</table>
							${
								others.length
									? `<h6>${__("Other open tasks")}</h6><ul>${others
											.map(
												(t) =>
													`<li>${this.todo_link(t)} <span class="cb-sub">${this.dt(
														t.date
													)}</span></li>`
											)
											.join("")}</ul>`
									: ""
							}`,
					},
				],
			});
			d.show();
		});
	}

	history_dialog(r) {
		this.call("get_history", { contact: r.contact }).then((res) => {
			const { results, todos } = res.message;
			const rh = results.length
				? results
						.map(
							(x) => `<tr><td>${this.E.doc_link({
								doctype: "Contact Call Result",
								name: x.name,
								label: this.dt(x.result_date),
							})}</td><td>${this.esc(__(x.result))}</td>
							<td>${this.esc(x.comment)}</td>
							<td>${x.military_unit ? this.E.military_unit(x.military_unit, { size: 18 }) : ""}</td>
							<td>${x.user ? this.E.user(x.user, { size: 18 }) : ""}</td></tr>`
						)
						.join("")
				: `<tr><td colspan="5" class="cb-sub">${__("No results")}</td></tr>`;
			const th = todos.length
				? todos
						.map(
							(x) => `<tr><td>${this.dt(x.date)}</td><td>${__(
								x.status
							)}</td><td>${this.todo_link(x)}</td>
							<td>${x.allocated_to ? this.E.user(x.allocated_to, { size: 18 }) : ""}</td></tr>`
						)
						.join("")
				: `<tr><td colspan="4" class="cb-sub">${__("No tasks")}</td></tr>`;
			new frappe.ui.Dialog({
				title: __("History"),
				size: "extra-large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "body",
						options: `${this.contact_header(r)}
							<h6>${__("Results")}</h6><table class="table table-sm">${rh}</table>
							<h6>${__("Tasks")}</h6><table class="table table-sm">${th}</table>`,
					},
				],
			}).show();
		});
	}

	finish_dialog(contact) {
		this.call("get_finish_summary", { contact }).then((res) => {
			const { before_open, changes, results } = res.message;
			const old = before_open.length
				? before_open
						.map(
							(t) =>
								`<div class="checkbox"><label><input type="checkbox" class="cb-close" value="${this.esc(
									t.name
								)}"> ${this.todo_link(t)} <span class="cb-sub">${this.dt(
									t.date
								)}</span></label></div>`
						)
						.join("")
				: `<div class="cb-sub">${__("No open tasks from before the work")}</div>`;
			const items = [
				...results.map(
					(x) => `<li><b>${__("Result")}:</b> ${this.esc(__(x.result))} ${this.esc(x.comment)}</li>`
				),
				...changes.map(
					(t) => `<li><b>${t.change === "created" ? __("New task") : __("Task closed")}:</b>
						${this.todo_link(t)} <span class="cb-sub">${this.dt(t.date)}</span></li>`
				),
			];
			const d = new frappe.ui.Dialog({
				title: __("Finish Contact"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "body",
						options: `<h6>${__("Changes during work")}</h6>
							<ul>${items.join("") || `<li class="cb-sub">${__("No changes")}</li>`}</ul>
							<h6>${__("Tasks from before the work (tick to close)")}</h6>${old}`,
					},
				],
				primary_action_label: __("Save"),
				primary_action: () => {
					const close = d.$wrapper
						.find(".cb-close:checked")
						.map((_i, el) => el.value)
						.get();
					this.call("finish_contact", { contact, close_todos: close }).then(() => {
						d.hide();
						this.load();
					});
				},
			});
			d.show();
		});
	}
}
