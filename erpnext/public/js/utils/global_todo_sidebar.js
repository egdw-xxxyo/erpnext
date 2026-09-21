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

	erpnext.update_global_todo_sidebar_state();
};

erpnext.update_global_todo_sidebar_state = function () {
	const active = /^\/(desk|app)\/todo$/.test(window.location.pathname.replace(/\/$/, ""));
	$("#navbar-global-todo .standard-sidebar-item").toggleClass("active-sidebar", active);
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
