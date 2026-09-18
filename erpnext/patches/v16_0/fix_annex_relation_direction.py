# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Relations that said «the specification is an annex to its own annex».

A relation reads as a sentence — main document, type, related document — and the prototype
recorded the package of a specification the other way round: the specification as the main
document, each annex as the related one, with the only annex type the vocabulary had. Read
as written, every one of those rows claimed that the ТУ is an annex to its instruction.

The direction is inferred from the two document types rather than from the text, because
the text is what was wrong: a package member is never itself a specification, so a row
whose main document requires completeness and whose related document does not was entered
from the specification's card and means «Має додаток». A row the other way round says what
it means already and is left alone, which is also what makes a second run change nothing.
"""

import frappe

from erpnext.technical_documentation.constants import (
	DOCUMENT_DOCTYPE,
	RELATION_ANNEX_TO,
	RELATION_DOCTYPE,
	RELATION_HAS_ANNEX,
)


def execute():
	specifications = {}

	for row in frappe.get_all(
		RELATION_DOCTYPE,
		filters={"relation_type": RELATION_ANNEX_TO},
		fields=["name", "main_document", "related_document"],
	):
		if is_specification(row.main_document, specifications) and not is_specification(
			row.related_document, specifications
		):
			frappe.db.set_value(
				RELATION_DOCTYPE, row.name, "relation_type", RELATION_HAS_ANNEX, update_modified=False
			)


def is_specification(document, cache):
	if document not in cache:
		document_type = frappe.db.get_value(DOCUMENT_DOCTYPE, document, "document_type")
		cache[document] = bool(
			document_type
			and frappe.db.get_value("Technical Document Type", document_type, "requires_completeness")
		)

	return cache[document]
