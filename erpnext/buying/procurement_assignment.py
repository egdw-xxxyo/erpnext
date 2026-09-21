import json

import frappe
from frappe import _
from frappe.desk.form.assign_to import _add as core_add
from frappe.desk.form.assign_to import get as get_assignments
from frappe.utils import escape_html

PROCUREMENT_ASSIGNMENT_DOCTYPES = {
	"Material Request",
	"Consolidated Purchase Order",
	"Purchase Order",
	"Purchase Invoice",
	"Payment Request",
	"Payment Entry",
	"Purchase Receipt",
}


@frappe.whitelist()
def add(args=None):
	return _add(args, ignore_permissions=False)


def _add(args=None, *, ignore_permissions=False):
	args = frappe._dict(args or frappe.local.form_dict)
	if args.doctype not in PROCUREMENT_ASSIGNMENT_DOCTYPES:
		return core_add(args, ignore_permissions=ignore_permissions)

	users = frappe.parse_json(args.get("assign_to")) or []
	if not ignore_permissions:
		frappe.get_doc(args.doctype, args.name).check_permission()
	duplicates = [
		user
		for user in users
		if frappe.db.exists(
			"ToDo",
			{
				"reference_type": args.doctype,
				"reference_name": args.name,
				"status": "Open",
				"allocated_to": user,
			},
		)
	]
	new_users = [user for user in users if user not in duplicates]
	if new_users:
		filtered_args = frappe._dict(args)
		filtered_args.assign_to = new_users
		result = core_add(filtered_args, ignore_permissions=ignore_permissions)
	else:
		result = get_assignments(args)

	if duplicates:
		display_names = [frappe.get_cached_value("User", user, "full_name") or user for user in duplicates]
		user_list = "<br><br>" + "<br>".join(escape_html(name) for name in display_names)
		frappe.msgprint(_("Already in the following Users ToDo list:{0}").format(user_list))
	return result


@frappe.whitelist()
def add_multiple(args=None):
	args = frappe._dict(args or frappe.local.form_dict)
	for name in json.loads(args.name):
		doc_args = frappe._dict(args)
		doc_args.name = name
		add(doc_args)
