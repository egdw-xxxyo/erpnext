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
		this.work_mode = null;
		this.work_count = 0;
		this.data = { rows: [], processed: 0, total: 0 };
		this.selected = new Set();
		this.open_hidden = new Set();
		this.expanded = new Set();
		this.editing = null;
		this.sort = null;
		this.dup_key = null;
		this.col_filters = {};
		this.date_filters = {};
		this.manager_filter = "";
		this.page.main.html(`<div class="client-base">
			<div class="cb-tabs"></div>
			<div class="cb-toolbar"></div>
			<div class="cb-scroll"></div>
			<div class="cb-bottom"></div>
			<button class="btn btn-default cb-to-top" title="${__(
				"Scroll to top"
			)}"><i class="fa fa-arrow-up"></i></button></div>`);
		this.$root = this.page.main.find(".client-base");
		this.$toolbar = this.$root.find(".cb-toolbar");
		this.$tabs = this.$root.find(".cb-tabs");
		this.$body = this.$root.find(".cb-scroll");
		this.$bottom = this.$root.find(".cb-bottom");
		this.$top = this.$root.find(".cb-to-top");
		const toggle_top = () =>
			this.$top.toggleClass("visible", this.$body.scrollTop() > 200 || $(window).scrollTop() > 200);
		this.$body.on("scroll", frappe.utils.throttle(toggle_top, 100));
		$(window).on("scroll.client-base", frappe.utils.throttle(toggle_top, 100));
		this.$top.on("click", () => {
			this.$body.animate({ scrollTop: 0 }, 200);
			$("html, body").animate({ scrollTop: 0 }, 200);
		});
		this.columns = [
			{
				key: "unit",
				label: __("Military Unit"),
				group: true,
				val: (g) => String(g.unit || "").toLowerCase(),
			},
			{
				key: "unit_name",
				label: __("Military Unit Name"),
				group: true,
				val: (g) => String(g.unit_name || "").toLowerCase(),
			},
			{ key: "contact", label: __("Contact"), val: (r) => (r.full_name || r.contact).toLowerCase() },
			{ key: "phone", label: __("Phone"), val: (r) => r.display_phone || "" },
			{ key: "designation", label: __("Position"), val: (r) => (r.designation || "").toLowerCase() },
			{
				key: "last_result",
				label: __("Latest Result"),
				val: (r) => (r.last_result ? r.last_result.result_date : ""),
			},
			{
				key: "next_action",
				label: __("Next Action"),
				val: (r) => (r.next_action && r.next_action.date) || "9999",
			},
			{ key: "comment", label: __("Comment"), val: (r) => (r.cb_comment || "").toLowerCase() },
			{
				key: "manager",
				others: true,
				label: __("Responsible Manager"),
				val: (r) => this.user_name(r.cb_manager),
			},
			{
				key: "in_work",
				others: true,
				label: __("In Work"),
				val: (r) => (r.cb_working ? "0" + this.user_name(r.cb_working_by) : "1"),
			},
		];
		const texts = {
			unit: (g) => g.unit,
			unit_name: (g) => g.unit_name,
			contact: (r) => `${r.full_name || r.contact} ${r.call_sign || ""}`,
			phone: (r) => r.display_phone,
			last_result: (r) =>
				r.last_result
					? `${__(r.last_result.result)} ${r.last_result.comment || ""} ${this.dt(
							r.last_result.result_date
					  )}`
					: "",
			next_action: (r) =>
				r.next_action
					? `${this.plain(r.next_action.description)} ${this.dt(r.next_action.date)}`
					: "",
			comment: (r) => r.cb_comment,
		};
		const dates = {
			last_result: (r) => (r.last_result ? String(r.last_result.result_date).slice(0, 10) : ""),
			next_action: (r) =>
				r.next_action && r.next_action.date ? String(r.next_action.date).slice(0, 10) : "",
		};
		this.columns.forEach((c) => {
			c.text = texts[c.key];
			c.date = dates[c.key];
			c.phone = c.key === "phone";
		});
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

	user_name(u) {
		if (!u) return "\uffff";
		const info = (frappe.user_info && frappe.user_info(u)) || {};
		return String(info.fullname || u).toLowerCase();
	}

	selectable(r) {
		const me = frappe.session.user;
		if (r.cb_manager && r.cb_manager !== me) return false;
		if (r.cb_working && r.cb_working_by && r.cb_working_by !== me) return false;
		return true;
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
			mine: mk({ fieldtype: "Check", fieldname: "mine", label: __("My contacts"), change: reload }),
			unassigned: mk({
				fieldtype: "Check",
				fieldname: "unassigned",
				label: __("Unassigned"),
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
		try {
			this.show_filters = localStorage.getItem("client-base-filters") === "1";
		} catch (e) {
			this.show_filters = false;
		}
		this.$ftoggle = $(
			`<button class="btn btn-default btn-sm cb-filters-toggle">
				<i class="fa fa-filter"></i> ${__("Filters")} <span class="cb-fcount"></span></button>`
		).appendTo(this.$toolbar);
		this.$ftoggle.on("click", () => {
			this.show_filters = !this.show_filters;
			try {
				localStorage.setItem("client-base-filters", this.show_filters ? "1" : "0");
			} catch (e) {
				this.show_filters = !!this.show_filters;
			}
			this.render();
		});
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
		if (this.work_mode) return {};
		const g = (k) => this.f[k].get_value();
		return {
			favorite: g("favorite") ? 1 : 0,
			only_due: g("only_due") ? 1 : 0,
			dup_key: this.dup_key,
			manager: g("mine") ? "mine" : g("unassigned") ? "unassigned" : "",
		};
	}

	load() {
		const first = this.work_mode === null;
		if (first) this.work_mode = 1;
		return frappe
			.call({
				method: `${CB_API}.get_rows`,
				args: { filters: this.filters(), work_mode: this.work_mode },
			})
			.then((r) => {
				this.work_count = r.message.work_count || 0;
				if (first && !this.work_count) {
					this.work_mode = 0;
					return this.load();
				}
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
		if (this.sort && !this.sort_column().group) {
			const col = this.sort_column();
			const x = col.val(a);
			const y = col.val(b);
			if (x !== y) return (x < y ? -1 : 1) * this.sort.dir;
		}
		if (a.urgency !== b.urgency) return b.urgency - a.urgency;
		if (a.cb_favorite !== b.cb_favorite) return b.cb_favorite - a.cb_favorite;
		return (a.full_name || a.contact).localeCompare(b.full_name || b.contact);
	}

	visible_columns() {
		const own = this.work_mode || this.f.mine.get_value();
		return this.columns.filter((c) => !(c.others && own));
	}

	matches(col, obj) {
		const q = String(this.col_filters[col.key] || "")
			.trim()
			.toLowerCase();
		if (!q) return true;
		const text = String(col.text(obj) || "").toLowerCase();
		if (text.includes(q)) return true;
		if (col.phone) {
			const digits = q.replace(/\D/g, "");
			return !!digits && text.replace(/\D/g, "").includes(digits);
		}
		return false;
	}

	date_ranges() {
		return this.columns.filter((c) => {
			const f = this.date_filters[c.key];
			return c.date && f && (f.from || f.to);
		});
	}

	in_range(col, r) {
		const f = this.date_filters[col.key];
		const v = col.date(r);
		if (!v) return false;
		return (!f.from || v >= f.from) && (!f.to || v <= f.to);
	}

	active_filters() {
		return this.columns.filter((c) => c.text && String(this.col_filters[c.key] || "").trim());
	}

	sort_column() {
		return this.sort ? this.columns.find((c) => c.key === this.sort.key) : null;
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
		const active = this.active_filters();
		const group_f = active.filter((c) => c.group);
		const row_f = active.filter((c) => !c.group);
		let list = [...map.values()].filter((g) => g.rows.length || g.hidden);
		if (group_f.length) list = list.filter((g) => group_f.every((c) => this.matches(c, g)));
		if (this.manager_filter && this.visible_columns().some((c) => c.key === "manager")) {
			list.forEach((g) => (g.rows = g.rows.filter((r) => r.cb_manager === this.manager_filter)));
			list = list.filter((g) => g.rows.length);
		}
		if (row_f.length) {
			list.forEach((g) => (g.rows = g.rows.filter((r) => row_f.every((c) => this.matches(c, r)))));
			list = list.filter((g) => g.rows.length);
		}
		const ranges = this.date_ranges();
		list.forEach((g) =>
			g.rows.forEach(
				(r) => (r._match = ranges.length ? ranges.every((c) => this.in_range(c, r)) : false)
			)
		);
		if (ranges.length) list = list.filter((g) => g.rows.some((r) => r._match));
		list.forEach((g) => {
			g.rows.sort((a, b) => this.compare(a, b));
			g.urgency = Math.max(0, ...g.rows.filter((r) => !r.cb_hidden).map((r) => r.urgency));
		});
		const col = this.sort_column();
		if (col && col.group) {
			list.sort((a, b) => col.val(a).localeCompare(col.val(b)) * this.sort.dir);
		} else if (col) {
			const dir = this.sort.dir;
			const key = (g) => {
				const pool = g.rows.filter((r) => !r.cb_hidden);
				const vals = (pool.length ? pool : g.rows).map((r) => String(col.val(r)));
				if (!vals.length) return dir > 0 ? "\uffff" : "";
				return vals.reduce((m, v) => ((dir > 0 ? v < m : v > m) ? v : m));
			};
			list.forEach((g) => (g.sort_key = key(g)));
			list.sort(
				(a, b) =>
					(a.sort_key < b.sort_key ? -1 : a.sort_key > b.sort_key ? 1 : 0) * dir ||
					String(a.unit).localeCompare(String(b.unit))
			);
		} else {
			list.sort((a, b) => b.urgency - a.urgency || String(a.unit).localeCompare(String(b.unit)));
		}
		return list;
	}

	render() {
		this.$reset.toggle(!!this.dup_key);
		const d = this.data;
		this.$counter.html(
			`<span>${this.work_mode ? __("Worked") : __("Processed contacts")}: <b>${d.processed}/${
				d.total
			}</b></span>
			<span>${__("Processed military units")}: <b>${d.units_processed || 0}/${d.units_total || 0}</b></span>`
		);
		this.$toolbar.find(".cb-field").toggle(!this.work_mode);

		if (!this.data.rows.length) {
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
		const cols = this.visible_columns();
		const extra = (c, cell) => (c.key === "designation" ? cell : "");
		const th = (c) =>
			`<th class="cb-sortable cb-col-${c.key}" data-key="${c.key}">${c.label} ${arrow(
				c.key
			)}</th>${extra(c, '<th class="cb-col-add"></th>')}`;
		const range = (c) => {
			if (!c.date) return "";
			const slot = (side) => `<div class="cb-date-slot" data-key="${c.key}" data-side="${side}"></div>`;
			return `<div class="cb-range">${slot("from")}<span>–</span>${slot("to")}</div>`;
		};
		const fth = (c) =>
			`<th class="cb-filter-cell cb-col-${c.key}"><div class="cb-filter-line">${
				c.key === "manager" ? '<div class="cb-manager-slot"></div>' : ""
			}${
				c.text
					? `<input type="text" class="form-control input-xs cb-col-filter" data-key="${
							c.key
					  }" placeholder="${__("Filter")}" value="${this.esc(this.col_filters[c.key] || "")}">`
					: ""
			}${range(c)}</div></th>${extra(c, "<th></th>")}`;
		const head = (cell, check) =>
			`<tr>${cols
				.filter((c) => c.group)
				.map(cell)
				.join("")}${check}${cols
				.filter((c) => !c.group)
				.map(cell)
				.join("")}<th></th></tr>`;
		const all = this.work_mode ? "" : '<input type="checkbox" class="cb-all">';
		this.$body.html(`<table class="cb-table"><thead>
			${this.show_filters ? head(fth, '<th class="cb-check"></th>') : ""}
			${head(th, `<th class="cb-check">${all}</th>`)}
			</thead><tbody></tbody></table>`);
		this.mount_date_filters();
		this.mount_manager_filter();
		const $head = this.$body.find("thead tr");
		if (this.show_filters)
			$head
				.eq(1)
				.children("th")
				.css("top", `${$head.eq(0).outerHeight()}px`);
		this.render_rows();
		this.render_bottom();
	}

	mount_manager_filter() {
		const $slot = this.$body.find(".cb-manager-slot");
		if (!$slot.length) return;
		const control = frappe.ui.form.make_control({
			parent: $slot,
			df: {
				fieldtype: "Link",
				options: "User",
				fieldname: "manager_filter",
				placeholder: __("Responsible Manager"),
				only_select: 1,
				get_query: () => ({ query: `${CB_API}.manager_query` }),
				change: () => {
					const value = control.get_value() || "";
					if (value === this.manager_filter) return;
					this.manager_filter = value;
					this.render_rows();
				},
			},
			render_input: true,
		});
		control.refresh();
		if (this.manager_filter) control.set_value(this.manager_filter);
	}

	filter_count() {
		const dates = this.date_ranges().length;
		return this.active_filters().length + dates + (this.manager_filter ? 1 : 0);
	}

	mount_date_filters() {
		this.$body.find(".cb-date-slot").each((_i, el) => {
			const key = el.getAttribute("data-key");
			const side = el.getAttribute("data-side");
			const current = (this.date_filters[key] || {})[side] || "";
			const control = frappe.ui.form.make_control({
				parent: $(el),
				df: {
					fieldtype: "Date",
					fieldname: `${key}_${side}`,
					placeholder: side === "from" ? __("From") : __("To"),
					change: () => {
						const value = control.get_value() || "";
						const f = this.date_filters[key] || {};
						if ((f[side] || "") === value) return;
						this.date_filters[key] = Object.assign({}, f, { [side]: value });
						this.render_rows();
					},
				},
				render_input: true,
			});
			control.refresh();
			if (current) control.set_value(current);
		});
	}

	render_rows() {
		const ncols = this.visible_columns().length + 3;
		const groups = this.groups();
		let html = "";
		if (!groups.length) {
			html = `<tr><td colspan="${ncols + 1}" class="cb-empty">${__("Nothing found")}</td></tr>`;
		}
		groups.forEach((g) => {
			const unit_cells = this.unit_cells(g);
			if (!g.rows.length) {
				html += `<tr class="cb-row cb-first cb-only-hidden">
					${unit_cells}<td class="cb-check"></td>
					<td colspan="${ncols - 3}" class="cb-sub">${__("All contacts are hidden")}</td></tr>`;
				return;
			}
			g.rows.forEach((r, i) => (html += this.row_html(r, i === 0 ? unit_cells : null)));
		});
		this.$body.find("tbody").html(html);
		const n = this.filter_count();
		this.$ftoggle.toggleClass("active", this.show_filters).toggleClass("btn-primary-light", n > 0);
		this.$ftoggle.find(".cb-fcount").text(n ? `(${n})` : "");
	}

	unit_cells(g) {
		const span = Math.max(1, g.rows.length);
		const visible = g.rows.filter((r) => !r.cb_hidden).length;
		const hidden = g.hidden
			? `<div class="cb-hidden-note">${__("{0} hidden", [g.hidden])}
				<button class="btn btn-xs btn-default cb-toggle-hidden" data-unit="${this.esc(g.unit)}">${
					this.open_hidden.has(g.unit) ? __("Hide") : __("Show")
			  }</button></div>`
			: "";
		return `<td class="cb-unit cb-col-unit" rowspan="${span}">
				${this.E.military_unit({ name: g.unit, sub: __("{0} contacts", [visible]) }, { card: true, size: 32 })}
				${hidden}</td>
			<td class="cb-unit cb-col-unit_name" rowspan="${span}">${this.esc(g.unit_name)}</td>`;
	}

	row_class(r) {
		const cls = [];
		if (this.work_mode && r.cb_done) cls.push("cb-done");
		else if (r.urgency === 2) cls.push("cb-overdue");
		else if (r.urgency === 1) cls.push("cb-today");
		if (r.cb_hidden && !this.work_mode) cls.push("cb-is-hidden");
		if (r._match) cls.push("cb-match");
		if (!this.work_mode && this.selected.has(r.contact)) cls.push("cb-selected");
		return cls.join(" ");
	}

	row_html(r, unit_cells) {
		const dup = r.dup_count
			? `<a class="cb-dup" data-key="${this.esc(r.dup_key)}">(${r.dup_count})</a>`
			: "";
		const contact = this.E.contact(
			{
				contact: r.contact,
				full_name: r.full_name || r.contact,
				image: r.image,
				sub: r.call_sign ? `«${r.call_sign}»` : "",
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
		const can = this.selectable(r);
		const check = this.work_mode
			? ""
			: `<input type="checkbox" class="cb-sel" ${this.selected.has(r.contact) ? "checked" : ""} ${
					can
						? ""
						: `disabled title="${__(
								"Only your own or unassigned contacts can be taken to work"
						  )}"`
			  }>`;
		const manager = `<div class="cb-manager">${
			r.cb_manager
				? this.E.user(r.cb_manager, { size: 22 })
				: `<span class="cb-sub">${__("Unassigned")}</span>`
		}<i class="fa fa-pencil cb-icon cb-manager-edit" title="${__("Change manager")}"></i></div>`;
		const in_work = r.cb_working
			? `<span class="indicator-pill ${r.cb_done ? "green" : "orange"}">${
					r.cb_done ? __("Finished") : __("In Work")
			  }</span> ${r.cb_working_by ? this.E.user(r.cb_working_by, { size: 20 }) : ""}`
			: "";
		const actions = this.work_mode
			? `<button class="btn btn-xs ${r.cb_done ? "btn-success" : "btn-primary"} cb-finish">${
					r.cb_done ? __("Finished") : __("Finish")
			  }</button>`
			: `<i class="fa ${r.cb_hidden ? "fa-eye" : "fa-eye-slash"} cb-icon cb-hide" title="${
					r.cb_hidden ? __("Unhide") : __("Hide")
			  }"></i>`;
		return `<tr class="cb-row ${unit_cells ? "cb-first" : ""} ${this.row_class(
			r
		)}" data-contact="${this.esc(r.contact)}" data-unit="${this.esc(r.unit)}">
			${unit_cells || ""}<td class="cb-check"><div class="cb-check-line">${check}
				<i class="fa ${r.cb_favorite ? "fa-star active" : "fa-star-o"} cb-icon cb-fav" title="${__(
			"Favorite"
		)}"></i></div></td>
			<td class="cb-col-contact">${contact}${dup}</td>
			<td class="cb-col-phone">${phone}</td>
			<td class="cb-col-designation">${this.esc(r.designation)}</td>
			<td class="cb-col-add"><button class="btn btn-xs btn-default cb-result">${__("Add Result")}</button></td>
			<td class="cb-col-last_result">${lr}</td>
			<td class="cb-col-next_action">${na}</td>
			<td class="cb-col-comment">${this.comment_html(r)}</td>
			${
				this.visible_columns().some((c) => c.others)
					? `<td class="cb-col-manager">${manager}</td>
			<td class="cb-col-in_work">${in_work}</td>`
					: ""
			}
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

	render_tabs() {
		const tab = (mode, label) =>
			`<button class="cb-tab ${
				this.work_mode === mode ? "active" : ""
			}" data-mode="${mode}">${label}</button>`;
		this.$tabs.html(
			tab(1, `${__("In Work")} <span class="cb-tab-count">${this.work_count}</span>`) +
				tab(0, __("List"))
		);
	}

	switch_tab(mode) {
		if (mode === this.work_mode) return;
		this.work_mode = mode;
		this.sort = null;
		this.editing = null;
		this.load();
	}

	render_bottom() {
		this.render_tabs();
		if (this.work_mode) {
			this.$bottom.html(
				this.work_count
					? `<button class="btn btn-danger cb-finish-work">${__("Finish Work")}</button>`
					: ""
			);
		} else if (this.selected.size) {
			this.$bottom.html(
				`<button class="btn btn-primary cb-start">${__("Add to Work")} (${
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
		const refilter = frappe.utils.debounce(() => this.render_rows(), 150);
		root.on("input", ".cb-col-filter", (e) => {
			this.col_filters[$(e.currentTarget).attr("data-key")] = e.currentTarget.value;
			refilter();
		});
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
			this.$body
				.find(`tr.cb-row[data-contact="${CSS.escape(r.contact)}"]`)
				.toggleClass("cb-selected", e.currentTarget.checked)
				.find(".cb-sel")
				.prop("checked", e.currentTarget.checked);
			this.render_bottom();
		});
		root.on("change", ".cb-all", (e) => {
			const on = e.currentTarget.checked;
			this.groups().forEach((g) =>
				g.rows
					.filter((r) => this.selectable(r))
					.forEach((r) => (on ? this.selected.add(r.contact) : this.selected.delete(r.contact)))
			);
			this.render();
		});
		root.on("click", ".cb-manager-edit", (e) => this.manager_dialog(this.row_of(e.currentTarget)));
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
		root.on("click", ".cb-tab", (e) => this.switch_tab(Number($(e.currentTarget).attr("data-mode"))));
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

	manager_dialog(r) {
		const d = new frappe.ui.Dialog({
			title: __("Change manager"),
			fields: [
				{ fieldtype: "HTML", fieldname: "info", options: this.contact_header(r) },
				{
					fieldtype: "Link",
					fieldname: "manager",
					label: __("Responsible Manager"),
					options: "User",
					default: r.cb_manager || frappe.session.user,
					get_query: () => ({ filters: { enabled: 1, user_type: "System User" } }),
				},
			],
			primary_action_label: __("Save"),
			primary_action: (v) => {
				this.call("set_manager", { contact: r.contact, manager: v.manager || "" }).then(() => {
					d.hide();
					this.load();
				});
			},
		});
		d.show();
	}

	toggle_flag(e, field) {
		const r = this.row_of(e.currentTarget);
		this.call("set_flag", { contact: r.contact, field, value: r[field] ? 0 : 1 }, false).then(() =>
			this.load()
		);
	}

	start_work() {
		const count = this.selected.size;
		this.call("start_work", { contacts: [...this.selected] }).then(() => {
			this.selected.clear();
			frappe.show_alert({ message: __("Added to work: {0}", [count]), indicator: "green" });
			this.load();
		});
	}

	finish_work() {
		frappe.confirm(__("Finish work? All contacts will no longer be marked as in work."), () => {
			this.call("finish_work").then(() => this.switch_tab(0));
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
				{ fieldtype: "Date", fieldname: "next_date", label: __("Date") },
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
								${row(__("Date"), this.dt(next.date))}
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
