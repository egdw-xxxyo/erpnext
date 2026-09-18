# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""«Пропозиція» rules layered on the stock Opportunity through hooks.

The Opportunity controller itself is left alone — everything here is wired in
erpnext/hooks.py (`doc_events`, `has_permission`, `scheduler_events`)."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

#: Set by the system when a Quotation is raised; never selectable by hand.
CONVERTED_STATUS = "Converted to Quotation"

#: Statuses that close an Opportunity. Read-only for everyone but a Sales Manager, and
#: excluded from the default list view.
FINAL_STATUSES = (CONVERTED_STATUS, "Lost")

#: Stock option names still passed by stock callers (Quotation, Sales Order).
OPPORTUNITY_STATUS_ALIASES = {
	"Open": "New",
	"Replied": "New",
	"Closed": "Lost",
	"Quotation": CONVERTED_STATUS,
	"Converted": CONVERTED_STATUS,
}

#: Every active Opportunity has to carry a planned next action.
NEXT_ACTION_REQUIRED_FIELDS = ("next_action_type", "next_action_date")


def validate(doc, method=None):
	validate_conversion_status(doc)
	validate_lost_reason(doc)
	validate_next_action(doc)
	set_next_action_overdue(doc)


def validate_conversion_status(doc):
	"""`Converted to Quotation` is set by the system only, when a Quotation is created."""
	if doc.status != CONVERTED_STATUS:
		return

	if doc.flags.converting_to_quotation or has_quotation(doc):
		return

	frappe.throw(
		_(
			"Status {0} is set automatically when a Quotation is created and cannot be selected manually"
		).format(frappe.bold(_(CONVERTED_STATUS)))
	)


def validate_lost_reason(doc):
	if doc.status == "Lost" and not doc.get("order_lost_reason"):
		frappe.throw(
			_("{0} is mandatory when the status is {1}").format(
				frappe.bold(_("Reason for Losing the Opportunity")), frappe.bold(_("Lost"))
			),
			title=_("Missing Value"),
		)


def validate_next_action(doc):
	if doc.status in FINAL_STATUSES:
		return

	for fieldname in NEXT_ACTION_REQUIRED_FIELDS:
		if doc.get(fieldname):
			continue

		frappe.throw(
			_("{0} is mandatory while the Opportunity is active").format(
				frappe.bold(_(doc.meta.get_label(fieldname)))
			),
			title=_("Missing Value"),
		)


def set_next_action_overdue(doc):
	"""Persist the overdue flag so the list view can filter and indicate on it."""
	overdue = (
		doc.get("next_action_date")
		and getdate(doc.next_action_date) < getdate(nowdate())
		and doc.status not in FINAL_STATUSES
	)
	doc.next_action_overdue = 1 if overdue else 0


def has_quotation(doc):
	if frappe.db.exists("Quotation", {"opportunity": doc.name, "docstatus": ["<", 2]}):
		return True

	return bool(frappe.db.exists("Quotation Item", {"prevdoc_docname": doc.name, "parenttype": "Quotation"}))


def mark_converted_to_quotation(doc, method=None):
	"""Move every Opportunity behind a freshly created Quotation to its converted status."""
	names = {item.get("prevdoc_docname") for item in doc.get("items", [])}
	names.add(doc.get("opportunity"))

	for name in filter(None, names):
		status = frappe.db.get_value("Opportunity", name, "status")
		if not status or status in FINAL_STATUSES:
			continue

		frappe.db.set_value("Opportunity", name, "status", CONVERTED_STATUS)
		frappe.get_doc("Opportunity", name).add_comment(
			"Comment", _("Converted to Quotation {0}").format(doc.name)
		)


def has_permission(doc, ptype, user=None, debug=False):
	"""Make Opportunities in a final status read-only for everyone but a Sales Manager.

	Returns True to defer to the standard role permissions: a controller hook can
	only deny, and frappe treats any falsy return (including None) as a denial.
	"""
	if ptype not in ("write", "create", "delete"):
		return True

	if doc.get("status") not in FINAL_STATUSES:
		return True

	user = user or frappe.session.user
	if user == "Administrator":
		return True

	roles = frappe.get_roles(user)
	if "Sales Manager" in roles or "System Manager" in roles:
		return True

	return False


def refresh_overdue_flags():
	"""Daily job keeping `next_action_overdue` accurate without touching each Opportunity."""
	if not frappe.db.has_column("Opportunity", "next_action_overdue"):
		return

	frappe.db.sql(
		"""
		update `tabOpportunity`
		set next_action_overdue = case
			when next_action_date is not null
				and next_action_date < %(today)s
				and status not in %(final)s
			then 1 else 0 end
		""",
		{"today": nowdate(), "final": list(FINAL_STATUSES)},
	)
