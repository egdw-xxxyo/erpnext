import frappe
from frappe import _
from frappe.utils import cint

ITEM_DOCTYPE = "Consolidated Purchase Order Item"
ORDER_DOCTYPE = "Consolidated Purchase Order"
LIKE_FIELD = "custom_item_liked"


@frappe.whitelist(methods=["POST"])
def set_item_like(order_name: str, item_name: str, liked: bool):
	order = frappe.get_doc(ORDER_DOCTYPE, order_name)
	order.check_permission("write")
	if not any(row.name == item_name for row in order.get("items", [])):
		frappe.throw(_("The item does not belong to this consolidated order."))
	value = int(bool(cint(liked)))
	# Cosmetic metadata only: do not save the order or trigger workflow/assignment hooks.
	frappe.db.set_value(ITEM_DOCTYPE, item_name, LIKE_FIELD, value, update_modified=False)
	return value


def preserve_item_likes(order):
	"""A regular save must not overwrite likes changed since the form was opened."""
	if order.is_new():
		return
	values = {
		row.name: row.get(LIKE_FIELD)
		for row in frappe.get_all(
			ITEM_DOCTYPE,
			filters={"parent": order.name, "parenttype": ORDER_DOCTYPE, "parentfield": "items"},
			fields=["name", LIKE_FIELD],
		)
	}
	for row in order.get("items", []):
		if row.name in values:
			row.set(LIKE_FIELD, values[row.name])
