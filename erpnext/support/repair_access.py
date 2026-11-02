"""Role setup and separation of repair intake from workshop work."""

import frappe
from frappe import _
from frappe.permissions import add_permission, update_permission_property

SUPPORT_ROLE = "Repair Support"
TECHNICIAN_ROLE = "Repair Technician"
ASSIGNMENT_RULE = "Ремонти: призначення прийнятих виробів"


def is_manager():
	return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()


def require_support():
	if not is_manager() and not ({SUPPORT_ROLE, "Support Team"} & set(frappe.get_roles())):
		frappe.throw(_("Only repair support can manage intake and delivery."), frappe.PermissionError)


def require_technician():
	if not is_manager() and TECHNICIAN_ROLE not in frappe.get_roles():
		frappe.throw(_("Only a repair technician can edit repair work."), frappe.PermissionError)


def setup():
	for role in (SUPPORT_ROLE, TECHNICIAN_ROLE):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)
	for name, roles in {
		"Ремонти: саппорт": [SUPPORT_ROLE, "Support Team"],
		"Ремонти: ремонтник": [TECHNICIAN_ROLE, "Stock User"],
	}.items():
		profile = (
			frappe.get_doc("Role Profile", name)
			if frappe.db.exists("Role Profile", name)
			else frappe.new_doc("Role Profile")
		)
		profile.role_profile = name
		changed = profile.is_new()
		existing = {row.role for row in profile.roles}
		for role in roles:
			if role not in existing:
				profile.append("roles", {"role": role})
				changed = True
		if changed:
			profile.save(ignore_permissions=True)
	for role, doctypes in {
		TECHNICIAN_ROLE: (
			"Issue",
			"Contact",
			"Customer",
			"Company",
			"Military Unit",
			"Issue Priority",
			"Issue Type",
			"Sales Order",
			"Lead",
			"Item",
			"Warehouse",
			"Repair Order",
		),
		SUPPORT_ROLE: (
			"Contact",
			"Customer",
			"Company",
			"Warehouse",
			"Item",
			"Military Unit",
			"Issue Priority",
			"Issue Type",
			"Sales Order",
			"Lead",
			"Repair Unit",
			"Repair Order",
			"Repair Movement",
			"Support Settings",
		),
	}.items():
		for doctype in doctypes:
			add_permission(doctype, role, ptype="read")
			update_permission_property(doctype, role, 0, "read", 1)
	for role in (SUPPORT_ROLE, TECHNICIAN_ROLE):
		add_permission("User", role, ptype="select")
		update_permission_property("User", role, 0, "select", 1)
	add_permission("Repair Unit", TECHNICIAN_ROLE, permlevel=1, ptype="read")
	update_permission_property("Repair Unit", TECHNICIAN_ROLE, 1, "read", 1)
	# Preserve existing rules and their manually maintained team configuration.
	if not frappe.db.exists("Assignment Rule", {"document_type": "Repair Unit"}):
		frappe.get_doc(
			{
				"doctype": "Assignment Rule",
				"name": ASSIGNMENT_RULE,
				"document_type": "Repair Unit",
				"rule": "Load Balancing",
				"custom_repair_assignee_role": TECHNICIAN_ROLE,
				"description": _("Take repair {0} into work.").format("{{ name }}"),
				"assign_condition": "status == 'Received' and not repair_user",
				"close_condition": "status in ('Ready for Dispatch', 'Dispatched', 'Delivered', 'Disposed')",
				"assignment_days": [
					{"day": day}
					for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
				],
			}
		).insert(ignore_permissions=True)


@frappe.whitelist()
def contact_details(contact: str):
	doc = frappe.get_doc("Contact", contact)
	doc.check_permission("read")
	phones = doc.get("phone_nos") or []
	emails = doc.get("email_ids") or []
	return {
		"phone": doc.mobile_no or doc.phone or next((row.phone for row in phones), ""),
		"email": doc.email_id or next((row.email_id for row in emails), ""),
	}
