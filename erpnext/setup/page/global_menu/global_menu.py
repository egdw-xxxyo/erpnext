import frappe
from frappe import _
from frappe.utils import cint


def check_manager():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_items() -> list[dict]:
	check_manager()
	rows = frappe.get_all(
		"Sidebar Menu Item",
		filters={"sidebar": ["is", "not set"]},
		fields=["name", "builtin", "label", "icon", "link_type", "link_to", "disabled", "required_doctype"],
		order_by="sort_order asc, creation asc",
	)
	for r in rows:
		r["roles"] = frappe.get_all(
			"Has Role", {"parent": r.name, "parenttype": "Sidebar Menu Item"}, pluck="role", order_by="idx"
		)
	return rows


@frappe.whitelist()
def reorder(names: str) -> None:
	check_manager()
	for idx, name in enumerate(frappe.parse_json(names), start=1):
		frappe.db.set_value("Sidebar Menu Item", name, "sort_order", idx * 10, update_modified=False)
	frappe.clear_cache()


@frappe.whitelist()
def set_disabled(name: str, disabled: int) -> None:
	check_manager()
	frappe.db.set_value("Sidebar Menu Item", name, "disabled", cint(disabled))
	frappe.clear_cache()
