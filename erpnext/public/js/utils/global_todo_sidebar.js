frappe.provide("erpnext");

erpnext.GLOBAL_MENU_BUILTINS = {
	Tasks: "#navbar-global-todo",
	Search: "#navbar-modal-search",
	Scanner: "#navbar-global-scanner",
	Notifications: ".standard-items-sections .sidebar-notification",
};

erpnext.mount_global_todo_sidebar = function () {
	if (frappe.session.user === "Guest") return;

	erpnext.mount_global_tasks_item();
	erpnext.mount_global_menu_items();
	erpnext.apply_global_menu_layout();
	erpnext.update_global_todo_sidebar_state();
};

erpnext.mount_global_tasks_item = function () {
	if ($("#navbar-global-todo").length) return;

	const user = frappe.session.user;
	const label = __("Tasks");
	const href = `/desk/todo?allocated_to=${encodeURIComponent(user)}`;
	const $item = $(`
		<div id="navbar-global-todo" class="sidebar-item-container" item-name="${label}"
			data-id="${label}" title="${label}" data-toggle="tooltip" data-placement="right">
			<div class="standard-sidebar-item">
				<a class="item-anchor" href="${href}">
					<span class="sidebar-item-icon text-ink-gray-7" item-icon="list">
						${frappe.utils.icon("list", "sm", "", "", "text-ink-gray-7 current-color", true)}
					</span>
					<span class="sidebar-item-label">${label}</span>
				</a>
			</div>
		</div>
	`);

	$item.on("click", "a", (event) => {
		event.preventDefault();
		frappe.route_options = { allocated_to: user };
		frappe.set_route("List", "ToDo");
	});

	const $container = $(".standard-items-sections").first();
	if (!$container.length) return;
	const $notification = $container.find(".sidebar-notification").first();
	if ($notification.length) {
		$notification.after($item);
	} else {
		$container.append($item);
	}
};

erpnext.global_menu_route = function (item) {
	if (item.link_type === "DocType") return ["List", item.link_to];
	if (item.link_type === "Report") return ["query-report", item.link_to];
	if (item.link_type === "Workspace") return [frappe.router.slug(item.link_to)];
	return [item.link_to];
};

erpnext.global_menu_dom_id = function (key) {
	return `navbar-global-menu-${String(key).replace(/[^A-Za-z0-9_-]/g, "_")}`;
};

erpnext.global_menu_icon = function (item) {
	const colored = /^#[0-9a-fA-F]{3,8}$/.test(item.icon_color || "");
	return frappe.utils.icon(
		item.icon,
		"sm",
		"",
		colored ? "color: " + item.icon_color : "",
		colored ? "current-color" : "text-ink-gray-7 current-color",
		true
	);
};

erpnext.mount_global_menu_items = function () {
	const $container = $(".standard-items-sections").first();
	if (!$container.length) return;

	(frappe.boot.global_sidebar_items || []).forEach((item) => {
		if (item.builtin) return;
		const id = erpnext.global_menu_dom_id(item.key);
		if ($(`#${id}`).length) return;

		const label = frappe.utils.escape_html(item.label);
		const is_url = item.link_type === "URL";
		const href = is_url
			? frappe.utils.escape_html(item.link_to)
			: "/desk/" + erpnext.global_menu_route(item).join("/").toLowerCase();
		const $item = $(`
			<div id="${id}" class="sidebar-item-container global-menu-item" item-name="${label}"
				data-id="${label}" data-link="${frappe.utils.escape_html(item.link_to)}"
				title="${label}" data-toggle="tooltip" data-placement="right">
				<div class="standard-sidebar-item">
					<a class="item-anchor" href="${href}">
						<span class="sidebar-item-icon text-ink-gray-7" item-icon="${item.icon}">
							${erpnext.global_menu_icon(item)}
						</span>
						<span class="sidebar-item-label">${label}</span>
					</a>
				</div>
			</div>
		`);
		if (!is_url) {
			$item.on("click", "a", (event) => {
				event.preventDefault();
				frappe.set_route(erpnext.global_menu_route(item));
			});
		}
		$container.append($item);
	});
};

erpnext.apply_global_menu_layout = function () {
	const $container = $(".standard-items-sections").first();
	if (!$container.length) return;

	const element = (item) =>
		item.builtin
			? $(erpnext.GLOBAL_MENU_BUILTINS[item.builtin]).first()
			: $(`#${erpnext.global_menu_dom_id(item.key)}`);

	(frappe.boot.hidden_builtin_items || []).forEach((key) => {
		$(erpnext.GLOBAL_MENU_BUILTINS[key]).each((_i, el) =>
			el.style.setProperty("display", "none", "important")
		);
	});

	const $dropdown = $container.children(".dropdown-notifications").first();
	let $prev = $dropdown.length ? $dropdown : null;
	(frappe.boot.global_sidebar_items || []).forEach((item) => {
		const $el = element(item);
		if (!$el.length) return;
		$el.each((_i, el) => el.style.removeProperty("display"));
		if ($prev) {
			$prev.after($el);
		} else {
			$container.prepend($el);
		}
		$prev = $el;
	});
};

erpnext.update_global_todo_sidebar_state = function () {
	const active = /^\/(desk|app)\/todo$/.test(window.location.pathname.replace(/\/$/, ""));
	$("#navbar-global-todo .standard-sidebar-item").toggleClass("active-sidebar", active);
	const path = window.location.pathname.toLowerCase();
	$(".global-menu-item").each(function () {
		const link = String($(this).data("link")).toLowerCase();
		$(this)
			.find(".standard-sidebar-item")
			.toggleClass("active-sidebar", path.endsWith("/" + link));
	});
};

$(document).on("toolbar_setup", () => erpnext.mount_global_todo_sidebar());

$(document).ready(() => {
	const try_mount = () => erpnext.mount_global_todo_sidebar();
	try_mount();
	[500, 1500, 3000].forEach((ms) => setTimeout(try_mount, ms));

	frappe.router.on("change", () => {
		try_mount();
		erpnext.update_global_todo_sidebar_state();
	});
});
