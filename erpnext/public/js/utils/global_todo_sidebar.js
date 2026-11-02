frappe.provide("erpnext");

erpnext.mount_global_todo_sidebar = function () {
	if (frappe.session.user === "Guest" || $("#navbar-global-todo").length) return;

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

	const $notification = $(".standard-items-sections .sidebar-notification").first();
	if ($notification.length) {
		$notification.after($item);
	} else {
		$(".standard-items-sections").first().append($item);
	}

	erpnext.mount_global_menu_items($item);
	erpnext.update_global_todo_sidebar_state();
};

erpnext.global_menu_route = function (item) {
	if (item.link_type === "DocType") return ["List", item.link_to];
	if (item.link_type === "Report") return ["query-report", item.link_to];
	if (item.link_type === "Workspace") return [frappe.router.slug(item.link_to)];
	return [item.link_to];
};

erpnext.mount_global_menu_items = function ($after) {
	let $anchor = $after;
	(frappe.boot.global_sidebar_items || []).forEach((item, idx) => {
		const id = `navbar-global-menu-${idx}`;
		if ($(`#${id}`).length) {
			$anchor = $(`#${id}`);
			return;
		}
		const is_url = item.link_type === "URL";
		const href = is_url
			? item.link_to
			: "/desk/" + erpnext.global_menu_route(item).join("/").toLowerCase();
		const $item = $(`
			<div id="${id}" class="sidebar-item-container global-menu-item" item-name="${frappe.utils.escape_html(
			item.label
		)}" data-id="${frappe.utils.escape_html(item.label)}" data-link="${frappe.utils.escape_html(
			item.link_to
		)}"
				data-type="${item.link_type}" title="${frappe.utils.escape_html(
			item.label
		)}" data-toggle="tooltip" data-placement="right">
				<div class="standard-sidebar-item">
					<a class="item-anchor" href="${frappe.utils.escape_html(href)}">
						<span class="sidebar-item-icon text-ink-gray-7" item-icon="${item.icon}">
							${frappe.utils.icon(item.icon, "sm", "", "", "text-ink-gray-7 current-color", true)}
						</span>
						<span class="sidebar-item-label">${frappe.utils.escape_html(item.label)}</span>
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
		$anchor.after($item);
		$anchor = $item;
	});
};

erpnext.update_global_todo_sidebar_state = function () {
	const active = /^\/(desk|app)\/todo$/.test(window.location.pathname.replace(/\/$/, ""));
	$("#navbar-global-todo .standard-sidebar-item").toggleClass("active-sidebar", active);
	$(".global-menu-item").each(function () {
		const $el = $(this);
		const link = String($el.data("link")).toLowerCase();
		const path = window.location.pathname.toLowerCase();
		$el.find(".standard-sidebar-item").toggleClass("active-sidebar", path.endsWith("/" + link));
	});
};

$(document).on("toolbar_setup", () => erpnext.mount_global_todo_sidebar());

$(document).ready(() => {
	const try_mount = () => erpnext.mount_global_todo_sidebar();
	try_mount();
	setTimeout(try_mount, 500);
	setTimeout(try_mount, 1500);

	frappe.router.on("change", () => {
		try_mount();
		erpnext.update_global_todo_sidebar_state();
	});
});
