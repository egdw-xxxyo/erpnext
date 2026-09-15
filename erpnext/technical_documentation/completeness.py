# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""How complete the documentation package of a specification is.

Computed on every call and stored nowhere. The state of a row depends on another
document's status, dates and current revision, so a saved percentage goes stale the
moment someone edits a card this one merely points at — which is exactly how the
hand-maintained mirror tables on dev drifted. Anything that needs completeness across
many documents at once goes through the report, which recomputes the same way.

Completeness is read off the document's relations, not guessed from titles: a required
type counts as present only when a related document of that type is effective and has a
current revision. The cost of that choice is explicit — a document that exists but was
never linked to the ТУ shows as missing — and it is the intended one, because the
alternative is matching documents by name and being quietly wrong.

The calculation reads every related document, permissions aside, so that two people
looking at the same specification are told the same thing about it — a percentage that
falls when a reader lacks access to one annex would be worse than useless in an ISO
register. What access does control is the link: a row pointing at a document the reader
may not open keeps its state and loses its name.

Four states rather than two, because «present» and «absent» cannot express a package that
is formally complete and materially out of date: a linked document past its review or
validity date reads «Прострочено», one that was superseded or archived «Не актуально».
"""

import frappe
from frappe.utils import getdate, today

from erpnext.technical_documentation.constants import (
	COMPLETENESS_EXPIRED,
	COMPLETENESS_MISSING,
	COMPLETENESS_OUTDATED,
	COMPLETENESS_PRESENT,
	DOCUMENT_DOCTYPE,
	DOCUMENT_EFFECTIVE,
	RELATION_DOCTYPE,
)

STATE_KEYS = {
	COMPLETENESS_PRESENT: "present",
	COMPLETENESS_EXPIRED: "expired",
	COMPLETENESS_OUTDATED: "outdated",
	COMPLETENESS_MISSING: "missing",
}

EMPTY = {"template": None, "rows": [], "required": 0, "present": 0}


@frappe.whitelist()
def get_completeness(document):
	frappe.has_permission(DOCUMENT_DOCTYPE, doc=document, throw=True)

	template = frappe.db.get_value(DOCUMENT_DOCTYPE, document, "requirement_template")
	if not template:
		return EMPTY

	requirements = frappe.get_all(
		"Document Requirement Item",
		filters={"parent": template, "parenttype": "Document Requirement Template"},
		fields=["document_type", "mandatory", "note"],
		order_by="idx",
	)

	related = get_related_by_type(document)
	rows = [build_row(requirement, related) for requirement in requirements]
	mandatory = [row for row in rows if row["mandatory"]]

	return {
		"template": template,
		"rows": rows,
		"required": len(mandatory),
		"present": sum(1 for row in mandatory if row["state"] == COMPLETENESS_PRESENT),
	}


def get_related_by_type(document):
	names = frappe.get_all(
		RELATION_DOCTYPE,
		filters={"main_document": document},
		pluck="related_document",
	)

	if not names:
		return {}

	related = {}
	for row in frappe.get_all(
		DOCUMENT_DOCTYPE,
		filters={"name": ("in", names)},
		fields=[
			"name",
			"document_title",
			"document_type",
			"status",
			"current_revision",
			"valid_until",
			"next_review_date",
		],
	):
		related.setdefault(row.document_type, []).append(row)

	return related


def build_row(requirement, related):
	candidates = related.get(requirement.document_type) or []
	states = [(candidate, state_of(candidate)) for candidate in candidates]

	best = next((pair for pair in states if pair[1] == COMPLETENESS_PRESENT), None)
	best = best or next((pair for pair in states if pair[1] == COMPLETENESS_EXPIRED), None)
	best = best or (states[0] if states else (None, COMPLETENESS_MISSING))

	document, state = best

	readable = bool(document) and frappe.has_permission(DOCUMENT_DOCTYPE, doc=document.name)

	return {
		"document_type": requirement.document_type,
		"mandatory": requirement.mandatory,
		"note": requirement.note,
		"document": document.name if readable else None,
		"document_title": document.document_title if readable else None,
		"restricted": bool(document) and not readable,
		"state": state,
		"state_key": STATE_KEYS[state],
	}


def state_of(document):
	if document.status != DOCUMENT_EFFECTIVE or not document.current_revision:
		return COMPLETENESS_OUTDATED

	for date in (document.valid_until, document.next_review_date):
		if date and getdate(date) < getdate(today()):
			return COMPLETENESS_EXPIRED

	return COMPLETENESS_PRESENT
