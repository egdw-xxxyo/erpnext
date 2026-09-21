"""Personal ToDo presets with date conditions evaluated on every query."""

import hashlib
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, today


@frappe.whitelist()
def ensure_default_filters():
	frappe.has_permission("ToDo", "read", throw=True)
	user = frappe.session.user
	presets = (
		("recent", _("Recently Added"), [["date", "last three days", "Last Three Days"]]),
		(
			"overdue",
			_("Overdue ToDo Tasks"),
			[["status", "=", "Open"], ["deadline", "is", "set"], ["deadline", "before now", "Now"]],
		),
		("today", _("Tasks for Today"), [["deadline", "next 24 hours", "Next 24 Hours"]]),
		("no-deadline", _("Tasks Without Deadlines"), [["deadline", "is", "not set"]]),
	)
	for key, label, conditions in presets:
		# Stable names make repeated visits and concurrent tabs idempotent.
		name = "todo-default-" + hashlib.sha256(f"{user}:{key}".encode()).hexdigest()[:32]
		if frappe.db.exists("List Filter", name):
			continue
		filters = [["ToDo", "allocated_to", "=", user]]
		filters.extend(["ToDo", *condition] for condition in conditions)
		frappe.get_doc(
			{
				"doctype": "List Filter",
				"reference_doctype": "ToDo",
				"filter_name": label,
				"for_user": user,
				"filters": frappe.as_json(filters),
			}
		).insert(set_name=name, ignore_if_duplicate=True)


@frappe.whitelist()
def get_recent_assignment_filter():
	# A Date field has no time: today and the two preceding calendar days.
	return {
		"fieldtype": "Select",
		"options": ["Last Three Days"],
		"operator": "between",
		"value": [add_days(today(), -2), today()],
	}


def prevent_default_filter_deletion(doc, method=None):
	if (
		doc.reference_doctype == "ToDo"
		and (doc.name or "").startswith("todo-default-")
		and frappe.session.user != "Administrator"
	):
		frappe.throw(_("Only Administrator can delete default ToDo filters."), frappe.PermissionError)


@frappe.whitelist()
def get_before_now_filter():
	return {
		"fieldtype": "Select",
		"options": ["Now"],
		"operator": "<",
		"value": str(now_datetime()),
	}


@frappe.whitelist()
def get_next_24_hours_filter():
	now = now_datetime()
	return {
		"fieldtype": "Select",
		"options": ["Next 24 Hours"],
		"operator": "between",
		"value": [str(now), str(now + timedelta(hours=24))],
	}


def upgrade_today_filters():
	"""Update existing built-in presets without changing users' other conditions."""
	old_condition = ["ToDo", "deadline", "Timespan", "today"]
	for row in frappe.get_all(
		"List Filter",
		filters={"reference_doctype": "ToDo", "name": ["like", "todo-default-%"]},
		fields=["name", "for_user", "filters"],
	):
		expected_name = "todo-default-" + hashlib.sha256(f"{row.for_user}:today".encode()).hexdigest()[:32]
		if row.name != expected_name:
			continue
		conditions = frappe.parse_json(row.filters) or []
		if old_condition not in conditions:
			continue
		conditions = [
			["ToDo", "deadline", "next 24 hours", "Next 24 Hours"] if f == old_condition else f
			for f in conditions
		]
		frappe.db.set_value("List Filter", row.name, "filters", frappe.as_json(conditions))


def upgrade_overdue_filters():
	"""Exclude completed and cancelled tasks from existing built-in overdue presets."""
	for row in frappe.get_all(
		"List Filter",
		filters={"reference_doctype": "ToDo", "name": ["like", "todo-default-%"]},
		fields=["name", "for_user", "filters"],
	):
		expected_name = "todo-default-" + hashlib.sha256(f"{row.for_user}:overdue".encode()).hexdigest()[:32]
		if row.name != expected_name:
			continue
		conditions = frappe.parse_json(row.filters) or []
		updated = [f for f in conditions if f[:2] != ["ToDo", "status"]]
		updated.append(["ToDo", "status", "=", "Open"])
		if updated != conditions:
			frappe.db.set_value("List Filter", row.name, "filters", frappe.as_json(updated))
