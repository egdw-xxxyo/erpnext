import frappe
from frappe.utils.nestedset import NestedSet


def keep_tree_position(doc, method=None):
	if not isinstance(doc, NestedSet) or doc.is_new():
		return

	old_parent_field = getattr(doc, "nsm_oldparent_field", "old_parent")
	fields = ["lft", "rgt", *([old_parent_field] if doc.meta.has_field(old_parent_field) else [])]
	stored = frappe.db.get_value(doc.doctype, doc.name, fields, as_dict=True, for_update=True)
	if stored:
		doc.update(stored)
