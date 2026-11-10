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
		this.work_mode = 0;
		this.data = { rows: [], processed: 0, total: 0 };
		this.selected = new Set();
		this.collapsed = new Set();
		this.dup_key = null;
		this.dup_label = null;
		this.page.main.html(`<div class="client-base"></div>`);
		this.$root = this.page.main.find(".client-base");
		this.$root.html(`
			<div class="cb-toolbar"></div>
			<div class="cb-body"></div>
			<div class="cb-bottom"></div>`);
		this.$toolbar = this.$root.find(".cb-toolbar");
		this.$body = this.$root.find(".cb-body");
		this.$bottom = this.$root.find(".cb-bottom");
		this.make_toolbar();
		this.bind();
	}

	esc(v) {
		return frappe.utils.escape_html(v === null || v === undefined ? "" : String(v));
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
			only_due: mk({
				fieldtype: "Check",
				fieldname: "only_due",
				label: __("Due Today"),
				change: reload,
			}),
			show_hidden: mk({
				fieldtype: "Check",
				fieldname: "show_hidden",
				label: __("Show Hidden"),
				change: reload,
			}),
		};
		this.$reset = $(
			`<button class="btn btn-default btn-sm cb-reset-dup" style="display:none">
				<i class="fa fa-times"></i> <span></span></button>`
		).appendTo(this.$toolbar);
		this.$counter = $('<div class="cb-counter"></div>').appendTo(this.$toolbar);
		this.$reset.on("click", () => {
			this.dup_key = null;
			this.dup_label = null;
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
			show_hidden: g("show_hidden") ? 1 : 0,
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

	render() {
		const rows = this.data.rows;
		this.$reset.toggle(!!this.dup_key);
		if (this.dup_key) this.$reset.find("span").text(__("Reset contact filter"));
		this.$counter.text(
			this.work_mode
				? `${__("Worked")}: ${this.data.processed}/${this.data.total}`
				: `${__("Processed contacts")}: ${this.data.processed}/${this.data.total}`
		);
		this.$toolbar.find(".cb-field").toggle(!this.work_mode);

		if (!rows.length) {
			this.$body.html(
				`<div class="cb-empty">${
					this.work_mode ? __("No contacts in work") : __("No contacts")
				}</div>`
			);
			this.render_bottom();
			return;
		}

		const groups = new Map();
		rows.forEach((r) => {
			if (!groups.has(r.unit)) groups.set(r.unit, []);
			groups.get(r.unit).push(r);
		});

		const head = `<tr>
			<th style="width:30px">${this.work_mode ? "" : '<input type="checkbox" class="cb-all">'}</th>
			<th>${__("Contact")}</th><th>${__("Phone")}</th><th>${__("Position")}</th>
			<th>${__("Last Result")}</th><th>${__("Next Action")}</th><th></th></tr>`;
		let html = `<table><thead>${head}</thead><tbody>`;
		groups.forEach((list, unit) => {
			const closed = this.collapsed.has(unit);
			html += `<tr class="cb-group" data-unit="${this.esc(unit)}"><td colspan="7">
				<i class="fa fa-chevron-${closed ? "right" : "down"}"></i>
				${this.esc(unit)}<span class="cb-group-name">${this.esc(list[0].unit_name)} · ${
				list.length
			}</span></td></tr>`;
			if (!closed) list.forEach((r) => (html += this.row_html(r)));
		});
		html += "</tbody></table>";
		this.$body.html(html);
		this.render_bottom();
	}

	row_html(r) {
		const cls = this.work_mode && r.cb_done ? "cb-done" : r.due && !this.work_mode ? "cb-due" : "";
		const dup = r.dup_count
			? `<a class="cb-dup" data-key="${this.esc(r.dup_key)}" data-label="${this.esc(r.full_name)}">(${
					r.dup_count
			  })</a>`
			: "";
		const name = r.full_name || r.contact;
		const call = r.call_sign ? ` <span class="cb-sub">«${this.esc(r.call_sign)}»</span>` : "";
		const lr = r.last_result
			? `${this.esc(r.last_result.result)}<div class="cb-sub">${frappe.datetime.str_to_user(
					r.last_result.result_date
			  )}</div>`
			: "";
		const na = r.next_action
			? `${this.esc(r.next_action.description ? $("<div>").html(r.next_action.description).text() : "")}
			   <div class="cb-sub">${r.next_action.date ? frappe.datetime.str_to_user(r.next_action.date) : ""}</div>`
			: "";
		const check = this.work_mode
			? ""
			: `<input type="checkbox" class="cb-sel" ${this.selected.has(r.contact) ? "checked" : ""}>`;
		const opts = this.work_mode
			? `<button class="btn btn-xs btn-default cb-result">${__("Add Result")}</button>
			   <button class="btn btn-xs ${r.cb_done ? "btn-success" : "btn-primary"} cb-finish">${
					r.cb_done ? __("Finished") : __("Finish")
			  }</button>`
			: `<button class="btn btn-xs btn-default cb-result">${__("Add Result")}</button>
			   <i class="fa fa-star cb-icon cb-fav ${r.cb_favorite ? "active" : ""}" title="${__("Favorite")}"></i>
			   <i class="fa fa-eye-slash cb-icon cb-hide ${r.cb_hidden ? "active" : ""}" title="${__("Hide")}"></i>`;
		return `<tr class="cb-row ${cls}" data-contact="${this.esc(r.contact)}" data-unit="${this.esc(
			r.unit
		)}">
			<td>${check}</td>
			<td><a class="cb-name" href="/app/contact/${encodeURIComponent(r.contact)}">${this.esc(
			name
		)}</a>${call}${dup}</td>
			<td>${this.esc(r.display_phone)}</td>
			<td>${this.esc(r.designation)}</td>
			<td>${lr}</td>
			<td>${na}</td>
			<td class="cb-actions">${opts}
				<i class="fa fa-history cb-icon cb-history" title="${__("History")}"></i></td></tr>`;
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
	}

	row_of(el) {
		const $tr = $(el).closest("tr.cb-row");
		return { contact: $tr.data("contact"), unit: $tr.data("unit") };
	}

	row_data(contact, unit) {
		return this.data.rows.find((r) => r.contact === contact && r.unit === unit);
	}

	bind() {
		const root = this.$root;
		root.on("click", ".cb-group", (e) => {
			const unit = $(e.currentTarget).data("unit");
			this.collapsed.has(unit) ? this.collapsed.delete(unit) : this.collapsed.add(unit);
			this.render();
		});
		root.on("click", ".cb-dup", (e) => {
			e.preventDefault();
			const $a = $(e.currentTarget);
			this.dup_key = $a.data("key");
			this.dup_label = $a.data("label");
			this.load();
		});
		root.on("change", ".cb-sel", (e) => {
			const { contact } = this.row_of(e.currentTarget);
			e.currentTarget.checked ? this.selected.add(contact) : this.selected.delete(contact);
			this.render_bottom();
		});
		root.on("change", ".cb-all", (e) => {
			this.data.rows.forEach((r) =>
				e.currentTarget.checked ? this.selected.add(r.contact) : this.selected.delete(r.contact)
			);
			this.render();
		});
		root.on("click", ".cb-fav", (e) => this.toggle_flag(e, "cb_favorite"));
		root.on("click", ".cb-hide", (e) => this.toggle_flag(e, "cb_hidden"));
		root.on("click", ".cb-result", (e) => {
			const { contact, unit } = this.row_of(e.currentTarget);
			this.result_dialog(this.row_data(contact, unit));
		});
		root.on("click", ".cb-history", (e) => this.history_dialog(this.row_of(e.currentTarget).contact));
		root.on("click", ".cb-finish", (e) => this.finish_dialog(this.row_of(e.currentTarget).contact));
		root.on("click", ".cb-start", () => this.start_work());
		root.on("click", ".cb-finish-work", () => this.finish_work());
	}

	toggle_flag(e, field) {
		const { contact, unit } = this.row_of(e.currentTarget);
		const r = this.row_data(contact, unit);
		const value = r[field] ? 0 : 1;
		this.call("set_flag", { contact, field, value }, false).then(() => this.load());
	}

	start_work() {
		this.call("start_work", { contacts: [...this.selected] }).then(() => {
			this.selected.clear();
			this.work_mode = 1;
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

	result_dialog(r) {
		const d = new frappe.ui.Dialog({
			title: __("Add Result"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "info",
					options: `<div style="margin-bottom:8px"><b>${this.esc(r.full_name || r.contact)}</b>
						${r.call_sign ? `«${this.esc(r.call_sign)}»` : ""}<br>
						<span class="cb-sub">${this.esc(r.unit)} ${this.esc(r.unit_name)} · ${this.esc(r.display_phone)} · ${this.esc(
						r.designation
					)}</span></div>`,
				},
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

	history_dialog(contact) {
		this.call("get_history", { contact }).then((res) => {
			const { results, todos } = res.message;
			const dt = (v) => (v ? frappe.datetime.str_to_user(v) : "");
			const rh = results.length
				? results
						.map(
							(x) => `<tr><td>${dt(x.result_date)}</td><td>${this.esc(x.result)}</td>
							<td>${this.esc(x.comment)}</td><td>${this.esc(x.military_unit)}</td></tr>`
						)
						.join("")
				: `<tr><td colspan="4" class="cb-sub">${__("No results")}</td></tr>`;
			const th = todos.length
				? todos
						.map(
							(x) => `<tr><td>${dt(x.date)}</td><td>${__(x.status)}</td>
							<td><a href="/app/todo/${encodeURIComponent(x.name)}">${this.esc(
								$("<div>").html(x.description).text()
							)}</a></td></tr>`
						)
						.join("")
				: `<tr><td colspan="3" class="cb-sub">${__("No tasks")}</td></tr>`;
			const d = new frappe.ui.Dialog({
				title: __("History"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "body",
						options: `<h6>${__("Results")}</h6><table class="table table-sm">${rh}</table>
							<h6>${__("Tasks")}</h6><table class="table table-sm">${th}</table>`,
					},
				],
			});
			d.show();
		});
	}

	finish_dialog(contact) {
		this.call("get_finish_summary", { contact }).then((res) => {
			const { before_open, changes, results } = res.message;
			const dt = (v) => (v ? frappe.datetime.str_to_user(v) : "");
			const text = (v) =>
				this.esc(
					$("<div>")
						.html(v || "")
						.text()
				);
			const old = before_open.length
				? before_open
						.map(
							(
								t
							) => `<div class="checkbox"><label><input type="checkbox" class="cb-close" value="${this.esc(
								t.name
							)}">
							<span>${text(t.description)} <span class="cb-sub">${dt(t.date)}</span></span></label></div>`
						)
						.join("")
				: `<div class="cb-sub">${__("No open tasks from before the work")}</div>`;
			const ch =
				changes.length || results.length
					? results
							.map(
								(x) =>
									`<li><b>${__("Result")}:</b> ${this.esc(x.result)} ${text(
										x.comment
									)}</li>`
							)
							.join("") +
					  changes
							.map(
								(t) => `<li><b>${
									t.change === "created" ? __("New task") : __("Task closed")
								}:</b>
							${text(t.description)} <span class="cb-sub">${dt(t.date)}</span></li>`
							)
							.join("")
					: `<li class="cb-sub">${__("No changes")}</li>`;
			const d = new frappe.ui.Dialog({
				title: __("Finish Contact"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "body",
						options: `<h6>${__("Changes during work")}</h6><ul>${ch}</ul>
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
