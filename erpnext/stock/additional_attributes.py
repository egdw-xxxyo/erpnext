# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Generic validation for the reusable ``Additional Attribute Row`` child table.

Any DocType can carry per-record key/value metadata by adding a Table Custom Field with
``options = "Additional Attribute Row"``. This module keeps those rows consistent:
the picked value must belong to the picked attribute, and neither may be disabled.

Wired in hooks.py as ``doc_events["*"]["validate"]`` — it exits immediately for documents
that have no such table.
"""

import frappe
from frappe import _

ROW_DOCTYPE = "Additional Attribute Row"
ROW_FIELDNAME = "additional_attributes"
MANDATORY_CACHE_KEY = "additional_attributes_mandatory"


def validate_additional_attributes(doc, method=None):
	if doc.doctype in (ROW_DOCTYPE, "Additional Attribute", "Additional Attribute Value"):
		return

	rows = []
	for df in doc.meta.get_table_fields():
		if df.options == ROW_DOCTYPE:
			rows.extend(doc.get(df.fieldname) or [])

	if not rows:
		return

	for row in rows:
		if not row.attribute or not row.value:
			continue

		value = frappe.db.get_value(
			"Additional Attribute Value", row.value, ["attribute", "disabled"], as_dict=True
		)
		if not value:
			frappe.throw(
				_("Row {0}: Additional Attribute Value {1} does not exist").format(
					row.idx, frappe.bold(row.value)
				)
			)

		if value.attribute != row.attribute:
			frappe.throw(
				_("Row {0}: Value {1} belongs to attribute {2}, not {3}").format(
					row.idx, frappe.bold(row.value), frappe.bold(value.attribute), frappe.bold(row.attribute)
				)
			)

		if value.disabled:
			frappe.throw(_("Row {0}: Value {1} is disabled").format(row.idx, frappe.bold(row.value)))

		if frappe.db.get_value("Additional Attribute", row.attribute, "disabled"):
			frappe.throw(_("Row {0}: Attribute {1} is disabled").format(row.idx, frappe.bold(row.attribute)))


def get_mandatory_attributes():
	"""Enabled attributes that a serial-creating document must carry a value for.

	Cached because it is read once per item row on every Purchase Receipt save; the cache is
	dropped by `AdditionalAttribute.on_update` / `on_trash`.
	"""
	cached = frappe.cache().get_value(MANDATORY_CACHE_KEY)
	if cached is not None:
		return cached

	names = [
		d.name
		for d in frappe.get_all(
			"Additional Attribute",
			filters={"disabled": 0, "mandatory": 1},
			fields=["name"],
			order_by="attribute_name",
		)
	]
	frappe.cache().set_value(MANDATORY_CACHE_KEY, names)
	return names


def validate_mandatory_attributes(rows, label=None):
	"""Throw when a mandatory attribute has no value among `rows`.

	`label` prefixes the message with the position the user sees, e.g. "Row 2".
	"""
	mandatory = get_mandatory_attributes()
	if not mandatory:
		return

	filled = {row.attribute for row in (rows or []) if row.attribute and row.value}
	missing = [d for d in mandatory if d not in filled]
	if not missing:
		return

	names = ", ".join(frappe.bold(d) for d in missing)
	if label:
		frappe.throw(_("{0}: additional attribute {1} is mandatory").format(label, names))

	frappe.throw(_("Additional attribute {0} is mandatory").format(names))


def copy_attribute_rows_to(parenttype, parent, rows):
	"""Insert attribute rows under an existing document without re-saving it.

	Used for documents that were built with validations suppressed (the draft
	`Serial and Batch Bundle` a Purchase Receipt generates), where `save()` would put those
	validations back in the way. Attributes the target already carries are left alone.
	"""
	rows = [row for row in (rows or []) if row.attribute and row.value]
	if not rows:
		return 0

	existing = {
		d.attribute
		for d in frappe.get_all(
			ROW_DOCTYPE,
			filters={"parenttype": parenttype, "parent": parent},
			fields=["attribute"],
		)
	}
	idx = _last_row_idx(parenttype, [parent]).get(parent, 0)

	inserted = 0
	for row in rows:
		if row.attribute in existing:
			continue

		idx += 1
		_insert_row(parenttype, parent, idx, row)
		inserted += 1

	return inserted


def _insert_row(parenttype, parent, idx, row):
	frappe.get_doc(
		{
			"doctype": ROW_DOCTYPE,
			"parenttype": parenttype,
			"parentfield": ROW_FIELDNAME,
			"parent": parent,
			"idx": idx,
			"attribute": row.attribute,
			"value": row.value,
			"notes": row.notes,
		}
	).insert(ignore_permissions=True)


def _last_row_idx(parenttype, parents):
	return {
		d.parent: d.idx or 0
		for d in frappe.get_all(
			ROW_DOCTYPE,
			filters={"parenttype": parenttype, "parent": ("in", parents)},
			fields=["parent", "max(idx) as idx"],
			group_by="parent",
		)
	}


def apply_attributes_to_serials(serial_nos, rows):
	"""Write the given attribute rows onto every Serial No that lacks them.

	Serial Nos on the inward paths are written with `frappe.db.bulk_insert`, so there is no
	document to hang the children on at creation time — they are attached here afterwards.
	A serial that already carries a value for an attribute keeps it.
	"""
	serial_nos = [d for d in (serial_nos or []) if d]
	rows = [row for row in (rows or []) if row.attribute and row.value]
	if not serial_nos or not rows:
		return 0

	already = frappe.get_all(
		ROW_DOCTYPE,
		filters={"parenttype": "Serial No", "parent": ("in", serial_nos)},
		fields=["parent", "attribute"],
	)
	taken = {(d.parent, d.attribute) for d in already}

	last_idx = _last_row_idx("Serial No", serial_nos)

	applied = 0
	for serial_no in serial_nos:
		idx = last_idx.get(serial_no, 0)
		for row in rows:
			if (serial_no, row.attribute) in taken:
				continue

			idx += 1
			_insert_row("Serial No", serial_no, idx, row)
			applied += 1

	return applied


def validate_purchase_receipt_attributes(doc, method=None):
	"""Require serial attributes only when quality control approves the receipt.

	A buyer owns the draft and may only send it for quality review. Mandatory quality
	attributes therefore must not block the buyer's initial save or workflow action.
	"""
	workflow_state = doc.get("workflow_state")
	if getattr(doc, "_action", None) != "submit" and workflow_state not in {
		"На затвердженні",
		"Проведено",
	}:
		return

	if not get_mandatory_attributes():
		return

	serialized = any(
		item.item_code and frappe.get_cached_value("Item", item.item_code, "has_serial_no")
		for item in doc.get("items") or []
	)
	if not serialized:
		return

	validate_mandatory_attributes(doc.get(ROW_FIELDNAME))


def apply_bundle_attributes_to_serials(doc, method=None):
	"""Push a bundle's own attribute rows onto the serials it brought in.

	Safety net for the inward paths that do not go through the Purchase Receipt helper —
	the selector dialog, the CSV import and the scanner.
	"""
	if doc.type_of_transaction != "Inward":
		return

	rows = doc.get(ROW_FIELDNAME) or []
	if not rows:
		return

	apply_attributes_to_serials([entry.serial_no for entry in doc.entries], rows)
