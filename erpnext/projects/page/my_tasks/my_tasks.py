"""«Мої справи»: the current user's own ToDos — whatever is allocated to them, never anyone else's."""

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

VIEWS = ("today", "overdue", "upcoming", "all")
PAGE_LENGTH = 50
FIELDS = (
	"name",
	"description",
	"status",
	"priority",
	"date",
	"deadline",
	"remind_at",
	"reference_type",
	"reference_name",
	"assigned_by",
)


def _view_filters(view, include_closed=False):
	user = frappe.session.user
	start = get_datetime(getdate())
	end = start.replace(hour=23, minute=59, second=59)
	filters = [["allocated_to", "=", user]]
	if view == "overdue":
		return [*filters, ["status", "=", "Open"], ["deadline", "<", now_datetime()]]
	filters.append(["status", "in", ["Open", "Closed"] if include_closed else ["Open"]])
	if view == "today":
		filters.append(["deadline", "between", [start, end]])
	elif view == "upcoming":
		filters.append(["deadline", ">", end])
	return filters


@frappe.whitelist()
def get_tasks(view="today", include_closed=0, start=0):
	if view not in VIEWS:
		frappe.throw(_("Unknown view: {0}").format(view))
	rows = frappe.get_list(
		"ToDo",
		filters=_view_filters(view, cint(include_closed)),
		fields=list(FIELDS),
		order_by="status desc, deadline asc, creation desc",
		start=cint(start),
		page_length=PAGE_LENGTH + 1,
	)
	now = now_datetime()
	for row in rows:
		row.is_overdue = row.status == "Open" and bool(row.deadline) and get_datetime(row.deadline) < now
	return {"tasks": rows[:PAGE_LENGTH], "has_more": len(rows) > PAGE_LENGTH, "counts": get_counts()}


@frappe.whitelist()
def get_counts():
	return {view: frappe.db.count("ToDo", _view_filters(view)) for view in VIEWS}


@frappe.whitelist()
def quick_add(
	description,
	deadline=None,
	remind_at=None,
	priority="Low",
	reference_type=None,
	reference_name=None,
):
	description = (description or "").strip()
	if not description:
		frappe.throw(_("Describe the task"))
	if bool(reference_type) != bool(reference_name):
		frappe.throw(_("Select both the document type and the document"))
	if reference_type:
		frappe.has_permission(reference_type, "read", reference_name, throw=True)
	user = frappe.session.user
	doc = frappe.get_doc(
		{
			"doctype": "ToDo",
			"description": description,
			"allocated_to": user,
			"assigned_by": user,
			"priority": priority or "Low",
			"deadline": deadline or None,
			"remind_at": remind_at or None,
			"reference_type": reference_type or None,
			"reference_name": reference_name or None,
		}
	).insert()
	return doc.name


@frappe.whitelist()
def set_status(name, status):
	if status not in ("Open", "Closed"):
		frappe.throw(_("Unknown status: {0}").format(status))
	doc = frappe.get_doc("ToDo", name)
	if doc.allocated_to != frappe.session.user:
		frappe.throw(_("This task is not yours"), frappe.PermissionError)
	doc.status = status
	doc.save()
	return get_counts()
