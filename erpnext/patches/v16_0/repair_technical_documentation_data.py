# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Make the prototype's rows satisfy the rules the register is about to enforce.

Every step is a no-op on a site that never held the desk prototype — prod today — because
each one iterates rows that are not there. On dev it touches the seven demo documents the
prototype left behind, and it has to run before the validations land, or those documents
become unsavable.

Nothing is deleted. `relation_type` values that were used as completeness notes are mapped
onto the real relation vocabulary and the original text is preserved in `note`, so no
information is lost by the conversion. The duplicate relation and the two typeless ones are
left in place by explicit decision: the duplicate check applies from here on and does not
reach backwards.

Two repairs concern revisions. Every prototype revision sits in draft, so the seven that
are not marked as drafts are closed for editing here. And the pointer to the revision in
force is cleared wherever it names something that was never put into force — a revision of
another document, or one still in draft. Clearing rather than guessing is the point: a
wrong current revision is exactly what the register exists to prevent, and no rule can
infer which revision was meant.
"""

import frappe

from erpnext.technical_documentation.constants import (
	DOCUMENT_DOCTYPE,
	MODIFICATION_DOCTYPE,
	RELATION_ANNEX_TO,
	RELATION_DOCTYPE,
	RELATION_RELATED_TO,
	REVISION_DOCTYPE,
	REVISION_DRAFT,
	REVISION_EFFECTIVE,
)

NAMING_SERIES = {
	DOCUMENT_DOCTYPE: "TD-",
	REVISION_DOCTYPE: "TDR-",
	RELATION_DOCTYPE: "TDRL-",
	MODIFICATION_DOCTYPE: "PM-",
}

SECTION_BY_TYPE_PREFIX = (
	("Технічні умови", "Технічні умови"),
	("Інструкція", "Інструкції"),
	("Договір", "Договори"),
	("Регламент", "Регламенти"),
)
FALLBACK_SECTION = "Інше"


def execute():
	if not frappe.db.table_exists("Technical Document"):
		return

	align_naming_series()
	backfill_sections()
	backfill_responsible()
	submit_historical_revisions()
	clear_invalid_current_revisions()
	normalise_relation_types()


def backfill_sections():
	"""`section` becomes mandatory; the prototype had no such field, so every row is empty."""
	for row in frappe.get_all(
		"Technical Document", filters={"section": ("in", (None, ""))}, fields=["name", "document_type"]
	):
		section = section_for(row.document_type)
		if section:
			frappe.db.set_value("Technical Document", row.name, "section", section, update_modified=False)


def section_for(document_type):
	default = frappe.db.get_value("Technical Document Type", document_type, "default_section")
	if default:
		return default

	for prefix, section in SECTION_BY_TYPE_PREFIX:
		if (document_type or "").startswith(prefix):
			return section if frappe.db.exists("Technical Document Section", section) else None

	return FALLBACK_SECTION if frappe.db.exists("Technical Document Section", FALLBACK_SECTION) else None


def backfill_responsible():
	"""The prototype had no responsible field at all — the document's creator is the only honest guess."""
	for row in frappe.get_all(
		"Technical Document", filters={"responsible": ("in", (None, ""))}, fields=["name", "owner"]
	):
		if row.owner and frappe.db.exists("User", row.owner):
			frappe.db.set_value(
				"Technical Document", row.name, "responsible", row.owner, update_modified=False
			)


def submit_historical_revisions():
	"""Everything the prototype left behind sits in draft, including revisions marked as in force.

	`docstatus` is set directly rather than through `submit()`: the rows predate the rules the
	controller now enforces, and a patch that runs business logic over historical data either
	rewrites it or aborts the migration. Submitting here only closes them for editing, which is
	the state they should have been in all along.
	"""
	if not frappe.db.table_exists(REVISION_DOCTYPE):
		return

	for name in frappe.get_all(
		REVISION_DOCTYPE,
		filters={"docstatus": 0, "revision_status": ("!=", REVISION_DRAFT)},
		pluck="name",
	):
		frappe.db.set_value(REVISION_DOCTYPE, name, "docstatus", 1, update_modified=False)


def clear_invalid_current_revisions():
	"""A pointer may only name a revision of this document that is submitted and in force."""
	for row in frappe.get_all(
		"Technical Document",
		filters={"current_revision": ("is", "set")},
		fields=["name", "current_revision"],
	):
		revision = frappe.db.get_value(
			REVISION_DOCTYPE,
			row.current_revision,
			["technical_document", "docstatus", "revision_status"],
			as_dict=True,
		)
		valid = (
			revision
			and revision.technical_document == row.name
			and revision.docstatus == 1
			and revision.revision_status == REVISION_EFFECTIVE
		)
		if not valid:
			frappe.db.set_value(
				"Technical Document", row.name, "current_revision", None, update_modified=False
			)


def normalise_relation_types():
	"""Free text used as a completeness marker becomes a real relation type, text kept in `note`."""
	for row in frappe.get_all("Technical Document Relation", fields=["name", "relation_type", "note"]):
		current = (row.relation_type or "").strip()
		if current in frappe.get_meta("Technical Document Relation").get_field("relation_type").options.split(
			"\n"
		):
			continue

		mapped = RELATION_ANNEX_TO if current else RELATION_RELATED_TO
		note = " · ".join(part for part in (row.note, current) if part)
		frappe.db.set_value(
			"Technical Document Relation",
			row.name,
			{"relation_type": mapped, "note": note or None},
			update_modified=False,
		)


def align_naming_series():
	"""Move each counter past the rows that arrived with their names already assigned.

	Rows codified out of dev carry names their target site never issued, so its counter
	still stands at zero and the first record created after the deployment is handed a
	name that is already taken — the register's very first relation fails to save. The
	counter is only ever moved forward, so a site that issued the names itself is left
	alone and a second run changes nothing.
	"""
	for doctype, prefix in NAMING_SERIES.items():
		if not frappe.db.table_exists(doctype):
			continue

		for key, highest in highest_issued(doctype, prefix).items():
			frappe.db.sql(
				"""insert into `tabSeries` (name, current) values (%s, %s)
				on duplicate key update current = greatest(current, %s)""",
				(key, highest, highest),
			)


def highest_issued(doctype, prefix):
	highest = {}
	for name in frappe.get_all(doctype, pluck="name"):
		if not name.startswith(prefix):
			continue

		series, _, suffix = name.rpartition("-")
		if not suffix.isdigit():
			continue

		key = f"{series}-"
		highest[key] = max(highest.get(key, 0), int(suffix))

	return highest
