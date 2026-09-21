# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Reading and writing the notes managers leave about their people.

Nothing here decides who may see a note: the reporting line of the Attendance Sheet page
is the only gate there is, and it is checked by the whitelisted methods that call in here.
The notes themselves belong to the employee, so a manager who inherits somebody inherits
what was written about them.
"""

import frappe
from frappe.query_builder.functions import Count
from frappe.utils import cstr

DOCTYPE = "Attendance Sheet Note"


def get_note_counts(employees: list[str]) -> dict[str, int]:
	"""How many notes each of these employees carries, absent from the map when none.

	The sheet marks the rows that have something to read, and a count per row is one
	query for the whole page rather than one for every name in it.
	"""
	if not employees:
		return {}

	Note = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(Note)
		.select(Note.employee, Count(Note.name).as_("count"))
		.where(Note.employee.isin(employees))
		.groupby(Note.employee)
	).run(as_dict=True)

	return {row.employee: row.count for row in rows}


def get_notes(employee: str) -> list[dict]:
	"""Every note about this employee, newest first, with who wrote each one."""
	notes = frappe.get_all(
		DOCTYPE,
		filters={"employee": employee},
		fields=["name", "note", "owner", "creation", "modified"],
		order_by="creation desc",
		ignore_permissions=True,
	)

	authors = get_author_names({note.owner for note in notes})

	return [
		{
			"name": note.name,
			"note": note.note,
			"author": authors.get(note.owner) or note.owner,
			"creation": cstr(note.creation),
			"edited": note.modified != note.creation,
			"mine": note.owner == frappe.session.user,
		}
		for note in notes
	]


def get_author_names(users: set[str]) -> dict[str, str]:
	"""The full names of the users who wrote the notes, keyed by user.

	A manager has no read permission on User, and the name of whoever wrote a note is
	the one thing about them the sheet shows.
	"""
	if not users:
		return {}

	authors = frappe.get_all(
		"User",
		filters={"name": ("in", list(users))},
		fields=["name", "full_name"],
		ignore_permissions=True,
	)

	return {author.name: author.full_name for author in authors}


def add_note(employee: str, note: str) -> str:
	doc = frappe.get_doc({"doctype": DOCTYPE, "employee": employee, "note": note})
	doc.insert(ignore_permissions=True)

	return doc.name


def update_note(name: str, note: str) -> None:
	doc = frappe.get_doc(DOCTYPE, name)
	doc.note = note
	doc.save(ignore_permissions=True)


def remove_note(name: str) -> None:
	frappe.delete_doc(DOCTYPE, name, ignore_permissions=True)
