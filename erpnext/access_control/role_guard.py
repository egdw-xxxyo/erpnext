import frappe
from frappe import _

from erpnext.access_control import permission_rules as rules

GUARDED_ROLE = "Access Manager"


def _roles(doc) -> list[str]:
	return [row.role for row in doc.get("roles") or []] if doc else []


def guard_access_manager_role(doc, method=None):
	if frappe.session.user == "Administrator":
		return
	if rules.changes_role(_roles(doc.get_doc_before_save()), _roles(doc), GUARDED_ROLE):
		frappe.throw(_("Only Administrator can grant or remove the Access Manager role"))
