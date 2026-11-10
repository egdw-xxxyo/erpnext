"""Backend of the «Клієнтська база» page: contacts grouped by military unit, work sessions, call results."""

import json
import re

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime, nowdate

ROLES = ("Sales Manager", "System Manager")
FLAGS = ("cb_favorite", "cb_hidden")


def _check():
	frappe.only_for(ROLES)


def _key(name, phone):
	digits = re.sub(r"\D", "", phone or "")
	if len(digits) >= 7:
		return "p:" + digits[-9:]
	return "n:" + (name or "").strip().lower()


def _loads(value):
	return json.loads(value) if isinstance(value, str) else (value or [])


def _base_rows():
	rows = frappe.db.sql(
		"""
		SELECT c.name AS contact, TRIM(CONCAT_WS(' ', c.first_name, c.last_name)) AS full_name,
			c.call_sign, c.designation, c.mobile_no, c.phone,
			c.cb_favorite, c.cb_hidden, c.cb_working, c.cb_done, c.cb_working_by, c.cb_work_started,
			c.cb_comment,
			dl.link_name AS unit, mu.name_of_military_unit AS unit_name
		FROM `tabContact` c
		JOIN `tabDynamic Link` dl
			ON dl.parent = c.name AND dl.parenttype = 'Contact' AND dl.link_doctype = 'Military Unit'
		LEFT JOIN `tabMilitary Unit` mu ON mu.name = dl.link_name
		""",
		as_dict=True,
	)
	if not rows:
		return rows

	names = list({r.contact for r in rows})
	first_phone = {}
	for p in frappe.get_all(
		"Contact Phone",
		filters={"parent": ["in", names], "parenttype": "Contact"},
		fields=["parent", "phone", "is_primary_mobile_no", "is_primary_phone"],
		order_by="idx asc",
	):
		best = first_phone.get(p.parent)
		primary = p.is_primary_mobile_no or p.is_primary_phone
		if best is None or (primary and not best[1]):
			first_phone[p.parent] = (p.phone, primary)

	units_by_key = {}
	for r in rows:
		r.display_phone = r.mobile_no or r.phone or (first_phone.get(r.contact) or ("",))[0]
		r.dup_key = _key(r.full_name or r.contact, r.display_phone)
		units_by_key.setdefault(r.dup_key, set()).add(r.unit)
	for r in rows:
		r.dup_count = len(units_by_key[r.dup_key] - {r.unit})
	return rows


def _last_results(contacts):
	out = {}
	if not contacts:
		return out
	for r in frappe.get_all(
		"Contact Call Result",
		filters={"contact": ["in", contacts]},
		fields=["contact", "result", "result_date", "comment"],
		order_by="result_date desc, creation desc",
	):
		out.setdefault(r.contact, r)
	return out


def _next_actions(contacts):
	out, counts = {}, {}
	if not contacts:
		return out, counts
	for t in frappe.get_all(
		"ToDo",
		filters={"reference_type": "Contact", "reference_name": ["in", contacts], "status": "Open"},
		fields=["name", "reference_name", "date", "description", "allocated_to", "priority"],
		order_by="creation asc",
	):
		counts[t.reference_name] = counts.get(t.reference_name, 0) + 1
		best = out.get(t.reference_name)
		if best is None or (t.date and (not best.date or getdate(t.date) < getdate(best.date))):
			out[t.reference_name] = t
	return out, counts


@frappe.whitelist()
def get_rows(filters=None, work_mode=0):
	_check()
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	work_mode = cint(work_mode)
	user = frappe.session.user
	today = getdate(nowdate())

	rows = _base_rows()
	if work_mode:
		rows = [r for r in rows if r.cb_working and r.cb_working_by == user]
	else:
		rows = [r for r in rows if not (r.cb_working and r.cb_working_by == user)]

	contacts = list({r.contact for r in rows})
	last = _last_results(contacts)
	nxt, open_counts = _next_actions(contacts)

	text = (filters.get("search") or "").strip().lower()
	out = []
	for r in rows:
		r.last_result = last.get(r.contact)
		r.next_action = nxt.get(r.contact)
		r.open_todos = open_counts.get(r.contact, 0)
		r.urgency = 0
		if r.next_action and r.next_action.date:
			due = getdate(r.next_action.date)
			r.urgency = 2 if due < today else 1 if due == today else 0
		if filters.get("military_unit") and r.unit != filters["military_unit"]:
			continue
		if filters.get("dup_key") and r.dup_key != filters["dup_key"]:
			continue
		if cint(filters.get("favorite")) and not r.cb_favorite:
			continue
		if cint(filters.get("only_due")) and not r.urgency:
			continue
		if filters.get("result") and (not r.last_result or r.last_result.result != filters["result"]):
			continue
		if text:
			hay = " ".join(
				str(v or "")
				for v in (
					r.full_name,
					r.call_sign,
					r.display_phone,
					r.designation,
					r.unit,
					r.unit_name,
					r.cb_comment,
				)
			).lower()
			if text not in hay:
				continue
		out.append(r)

	visible = [r for r in out if work_mode or not r.cb_hidden]
	processed = (
		sum(1 for r in visible if r.cb_done) if work_mode else sum(1 for r in visible if r.last_result)
	)
	return {"rows": out, "processed": processed, "total": len(visible)}


@frappe.whitelist()
def set_comment(contact, comment=None):
	_check()
	if not frappe.db.exists("Contact", contact):
		frappe.throw(_("Contact {0} not found").format(contact))
	frappe.db.set_value("Contact", contact, "cb_comment", comment or None, update_modified=False)
	return comment or ""


@frappe.whitelist()
def set_flag(contact, field, value):
	_check()
	if field not in FLAGS:
		frappe.throw(_("Invalid field"))
	frappe.db.set_value("Contact", contact, field, cint(value), update_modified=False)


@frappe.whitelist()
def start_work(contacts):
	_check()
	contacts = _loads(contacts)
	user = frappe.session.user
	if not contacts:
		frappe.throw(_("Select at least one contact"))
	busy = frappe.get_all(
		"Contact",
		filters={"name": ["in", contacts], "cb_working": 1, "cb_working_by": ["not in", [user, ""]]},
		fields=["name", "cb_working_by"],
	)
	if busy:
		frappe.throw(
			_("Contact {0} is already being worked on by {1}").format(busy[0].name, busy[0].cb_working_by)
		)
	started = now_datetime()
	for name in contacts:
		frappe.db.set_value(
			"Contact",
			name,
			{"cb_working": 1, "cb_done": 0, "cb_working_by": user, "cb_work_started": started},
			update_modified=False,
		)


def _own_working(contact):
	row = frappe.db.get_value(
		"Contact", contact, ["cb_working", "cb_working_by", "cb_work_started"], as_dict=True
	)
	if not row or not row.cb_working or row.cb_working_by != frappe.session.user:
		frappe.throw(_("Contact {0} is not in your work").format(contact))
	return row


@frappe.whitelist()
def add_result(
	contact,
	result,
	result_date=None,
	comment=None,
	unit=None,
	next_description=None,
	next_date=None,
	next_user=None,
):
	_check()
	todo_name = None
	if next_description or next_date:
		todo = frappe.new_doc("ToDo")
		todo.description = next_description or _("Follow up")
		todo.reference_type = "Contact"
		todo.reference_name = contact
		todo.date = next_date or None
		todo.allocated_to = next_user or frappe.session.user
		todo.insert(ignore_permissions=True)
		todo_name = todo.name

	doc = frappe.new_doc("Contact Call Result")
	doc.update(
		{
			"contact": contact,
			"military_unit": unit,
			"result": result,
			"result_date": result_date or now_datetime(),
			"comment": comment,
			"user": frappe.session.user,
			"next_todo": todo_name,
		}
	)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name, "next_todo": todo_name}


@frappe.whitelist()
def get_history(contact):
	_check()
	results = frappe.get_all(
		"Contact Call Result",
		filters={"contact": contact},
		fields=["name", "result", "result_date", "comment", "user", "military_unit", "next_todo"],
		order_by="result_date desc, creation desc",
	)
	todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Contact", "reference_name": contact},
		fields=["name", "status", "date", "description", "allocated_to", "priority", "creation"],
		order_by="creation desc",
	)
	return {"results": results, "todos": todos}


@frappe.whitelist()
def get_finish_summary(contact):
	_check()
	work = _own_working(contact)
	started = get_datetime(work.cb_work_started) if work.cb_work_started else add_to_date(None, days=-1)
	todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Contact", "reference_name": contact},
		fields=["name", "status", "date", "description", "allocated_to", "creation", "modified"],
		order_by="creation asc",
	)
	before_open, changes = [], []
	for t in todos:
		if get_datetime(t.creation) < started:
			if t.status == "Open":
				before_open.append(t)
			elif get_datetime(t.modified) >= started:
				t.change = "closed"
				changes.append(t)
		else:
			t.change = "created"
			changes.append(t)
	results = frappe.get_all(
		"Contact Call Result",
		filters={"contact": contact, "creation": [">=", started]},
		fields=["name", "result", "result_date", "comment", "next_todo"],
		order_by="result_date asc",
	)
	return {"before_open": before_open, "changes": changes, "results": results}


@frappe.whitelist()
def finish_contact(contact, close_todos=None):
	_check()
	_own_working(contact)
	for name in _loads(close_todos):
		todo = frappe.get_doc("ToDo", name)
		if todo.reference_type == "Contact" and todo.reference_name == contact and todo.status == "Open":
			todo.status = "Closed"
			todo.save(ignore_permissions=True)
	frappe.db.set_value("Contact", contact, "cb_done", 1, update_modified=False)


@frappe.whitelist()
def finish_work():
	_check()
	frappe.db.sql(
		"""
		UPDATE `tabContact`
		SET cb_working = 0, cb_done = 0, cb_working_by = NULL, cb_work_started = NULL
		WHERE cb_working = 1 AND cb_working_by = %s
		""",
		frappe.session.user,
	)
