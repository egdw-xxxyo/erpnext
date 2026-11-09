frappe.pages["global-menu"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Global Menu"),
		single_column: true,
	});
	new erpnext.GlobalMenuPage(page);
};

frappe.pages["global-menu"].on_page_show = function () {
	erpnext.global_menu_page && erpnext.global_menu_page.refresh();
};

erpnext.GlobalMenuPage = class GlobalMenuPage {
	constructor(page) {
		this.page = page;
		this.items = [];
		this.preview_role = null;
		erpnext.global_menu_page = this;
		this.make();
	}

	make() {
		this.page.set_primary_action(__("Add Item"), () => frappe.new_doc("Sidebar Menu Item"), "add");
		this.page.add_inner_button(__("Reload Menu"), () => window.location.reload());

		this.role_field = frappe.ui.form.make_control({
			parent: this.page.page_form,
			df: {
				fieldtype: "Link",
				options: "Role",
				fieldname: "preview_role",
				placeholder: __("View as role"),
				change: () => {
					this.preview_role = this.role_field.get_value() || null;
					this.render();
				},
			},
			render_input: true,
		});
		this.role_field.$wrapper.addClass("col-md-3");

		this.$body = $(`
			<div class="global-menu-page" style="max-width: 720px; margin: 0 auto; padding: 16px;">
				<p class="text-muted">${__("Drag to reorder. These entries appear at the top of every sidebar.")}</p>
				<div class="global-menu-list"></div>
			</div>
		`).appendTo(this.page.main);
		this.$list = this.$body.find(".global-menu-list");
	}

	refresh() {
		return frappe.xcall("erpnext.setup.page.global_menu.global_menu.get_items").then((items) => {
			this.items = items;
			this.render();
		});
	}

	visible_for_preview(item) {
		if (item.disabled) return false;
		if (!this.preview_role) return true;
		return !item.roles.length || item.roles.includes(this.preview_role);
	}

	render() {
		this.$list.empty();
		this.items.forEach((item) => {
			const shown = this.visible_for_preview(item);
			const roles = item.roles.length
				? item.roles
						.map((r) => `<span class="badge badge-default">${frappe.utils.escape_html(r)}</span>`)
						.join(" ")
				: `<span class="text-muted small">${__("Everyone")}</span>`;
			const label = frappe.utils.escape_html(__(item.label));
			const $row = $(`
				<div class="global-menu-row d-flex align-items-center" data-name="${item.name}"
					style="gap: 12px; padding: 10px 12px; margin-bottom: 6px; border: 1px solid var(--border-color);
					border-radius: var(--border-radius-md); background: var(--card-bg); opacity: ${shown ? 1 : 0.4};">
					<span class="drag-handle" style="cursor: grab;"><i class="fa fa-bars text-muted"></i></span>
					<span style="width: 20px; text-align: center;">
						${erpnext.global_menu_icon({ icon: item.icon || "list", icon_color: item.icon_color })}
					</span>
					<span class="flex-grow-1">
						<strong>${label}</strong>
						${item.builtin ? `<span class="text-muted small"> · ${__("built-in")}</span>` : ""}
						<div>${roles}</div>
					</span>
					<button class="btn btn-xs btn-default btn-toggle">
						${item.disabled ? __("Show") : __("Hide")}
					</button>
					<button class="btn btn-xs btn-default btn-edit">${__("Edit")}</button>
				</div>
			`);
			$row.find(".btn-edit").on("click", () =>
				frappe.set_route("Form", "Sidebar Menu Item", item.name)
			);
			$row.find(".btn-toggle").on("click", () => {
				frappe
					.xcall("erpnext.setup.page.global_menu.global_menu.set_disabled", {
						name: item.name,
						disabled: item.disabled ? 0 : 1,
					})
					.then(() => this.refresh());
			});
			this.$list.append($row);
		});

		if (this.sortable) this.sortable.destroy();
		this.sortable = Sortable.create(this.$list.get(0), {
			handle: ".drag-handle",
			animation: 150,
			onEnd: () => {
				const names = this.$list
					.find(".global-menu-row")
					.map((_i, el) => $(el).data("name"))
					.get();
				this.items.sort((a, b) => names.indexOf(a.name) - names.indexOf(b.name));
				frappe.xcall("erpnext.setup.page.global_menu.global_menu.reorder", {
					names: JSON.stringify(names),
				});
			},
		});
	}
};
