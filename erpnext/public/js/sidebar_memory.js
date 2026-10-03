const FRAPPE_SIDEBAR_MEMORY = "sidebar_item_map";
const SIDEBAR_CHOICES = "erpnext_sidebar_choices";

function read_json(key) {
	try {
		return JSON.parse(localStorage.getItem(key) || "{}");
	} catch {
		return {};
	}
}

function write_json(key, value) {
	try {
		localStorage.setItem(key, JSON.stringify(value));
	} catch {
		console.warn(`${key} was not saved`);
	}
}

function current_sidebar_choice(sidebar) {
	const entity = sidebar.entity_from_route(frappe.get_route());
	const title = sidebar.sidebar_title;
	const candidates = entity ? sidebar.get_workspace_sidebars(entity) : [];
	return candidates.length > 1 && candidates.includes(title) ? { entity, title } : null;
}

function remember_current_sidebar() {
	const sidebar = frappe.app && frappe.app.sidebar;
	const choice = sidebar && current_sidebar_choice(sidebar);
	if (!choice) return;
	write_json(SIDEBAR_CHOICES, { ...read_json(SIDEBAR_CHOICES), [choice.entity]: choice.title });
}

function restore_sidebar_choices() {
	const choices = Object.entries(read_json(SIDEBAR_CHOICES)).map(([entity, title]) => [entity, [title]]);
	write_json(FRAPPE_SIDEBAR_MEMORY, {
		...read_json(FRAPPE_SIDEBAR_MEMORY),
		...Object.fromEntries(choices),
	});
}

restore_sidebar_choices();

$(document).on("app_ready", () => {
	frappe.router.on("change", remember_current_sidebar);
	$(window).on("beforeunload", remember_current_sidebar);
});
