"""Permission-aware, paginated data for the ToDo planner."""

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

PAGE_SIZE = 100


@frappe.whitelist()
def get_tasks(
	start: str | datetime,
	end: str | datetime,
	filters: str | list | None = None,
	include_closed: bool | int | str = False,
	section: str = "calendar",
	offset: int | str = 0,
) -> dict:
	frappe.has_permission("ToDo", "read", throw=True)
	start, end = get_datetime(start), get_datetime(end)
	if not 0 < (end - start).total_seconds() <= 43 * 86400:
		frappe.throw(_("Invalid planner date range"))
	if section not in ("calendar", "overdue", "unscheduled"):
		frappe.throw(_("Invalid planner section"))
	filters = frappe.parse_json(filters) if isinstance(filters, str) else filters
	filters = filters or []
	if not isinstance(filters, list) or any(
		not isinstance(f, list | tuple) or len(f) not in (4, 5) or f[0] != "ToDo" for f in filters
	):
		frappe.throw(_("Invalid ToDo filters"))
	query_filters = [list(f[:4]) for f in filters]
	now = now_datetime()
	if section == "overdue":
		query_filters += [["ToDo", "status", "=", "Open"], ["ToDo", "deadline", "<", now]]
		query_filters.append(["ToDo", "deadline", "is", "set"])
	elif not any(f[1] == "status" for f in query_filters):
		query_filters.append(
			["ToDo", "status", "in", ["Open", "Closed"] if cint(include_closed) else ["Open"]]
		)
	if section == "calendar":
		query_filters += [["ToDo", "deadline", ">=", start], ["ToDo", "deadline", "<", end]]
	elif section == "unscheduled":
		query_filters.append(["ToDo", "deadline", "is", "not set"])
	tasks = frappe.get_list(
		"ToDo",
		filters=query_filters,
		fields=[
			"name",
			"description",
			"status",
			"priority",
			"date",
			"deadline",
			"allocated_to",
			"reference_type",
			"reference_name",
		],
		order_by="date desc, name asc" if section == "unscheduled" else "deadline asc, name asc",
		start=max(0, cint(offset)),
		page_length=PAGE_SIZE + 1,
	)
	for task in tasks:
		task.is_overdue = bool(task.status == "Open" and task.deadline and get_datetime(task.deadline) < now)
	return {"tasks": tasks[:PAGE_SIZE], "has_more": len(tasks) > PAGE_SIZE, "now": now}
