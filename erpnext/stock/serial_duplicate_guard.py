"""One serial number is one unit, so a document lists it once.

The scanner refuses a repeat only within the row it is filling, and a serial typed or pasted into
a row's text field is never checked. A box scanned twice on a Delivery Note then ships the same
unit twice on paper. This guard runs on save and counts every serial over all rows of the document.
"""

from collections import defaultdict

import frappe
from frappe import _

TABLES = ("items", "packed_items")
BUNDLE_FIELDS = ("serial_and_batch_bundle", "rejected_serial_and_batch_bundle")
TEXT_FIELDS = ("serial_no", "rejected_serial_no")


def _split(value):
	return [s.strip() for s in (value or "").splitlines() if s.strip()]


def _direction(row):
	"""A Stock Entry may consume a unit in one row and put it back in another; a repeat is per side."""
	source, target = row.get("s_warehouse"), row.get("t_warehouse")
	if source and target:
		return "transfer"
	return "out" if source else "in" if target else ""


def _rows(doc):
	for table in TABLES:
		for row in doc.get(table) or []:
			yield table, row


def _bundle_serials(doc):
	bundles = {row.get(f) for _t, row in _rows(doc) for f in BUNDLE_FIELDS if row.get(f)}
	serials = defaultdict(list)
	if bundles:
		for entry in frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": ["in", list(bundles)], "serial_no": ["is", "set"]},
			fields=["parent", "serial_no"],
		):
			serials[entry.parent].append(entry.serial_no)
	return serials


def _label(doc, table, row):
	field = doc.meta.get_field(table)
	prefix = f"{_(field.label)} " if table != "items" and field else ""
	return f"{prefix}#{row.idx}"


def validate_unique_serials(doc, method=None):
	"""`doc_events` validate on stock documents: a serial appears in one row, once."""
	bundle_serials = _bundle_serials(doc)
	seen = defaultdict(list)

	for table, row in _rows(doc):
		label = _label(doc, table, row)
		typed = [s for f in TEXT_FIELDS for s in _split(row.get(f))]
		repeated = sorted({s for s in typed if typed.count(s) > 1})
		if repeated:
			frappe.throw(
				_("Row {0}: serial numbers entered more than once: {1}").format(label, ", ".join(repeated)),
				title=_("Duplicate serial numbers"),
			)

		serials = set(typed)
		for field in BUNDLE_FIELDS:
			serials.update(bundle_serials.get(row.get(field), []))
		for serial in serials:
			seen[(serial, _direction(row))].append(label)

	duplicates = {serial: rows for (serial, _d), rows in seen.items() if len(rows) > 1}
	if not duplicates:
		return

	frappe.throw(
		"<br>".join(
			_("Serial No {0} is in rows {1}").format(serial, ", ".join(rows))
			for serial, rows in sorted(duplicates.items())
		),
		title=_("Duplicate serial numbers"),
	)
