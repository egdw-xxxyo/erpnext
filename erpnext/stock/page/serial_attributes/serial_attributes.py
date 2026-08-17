# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Backend for the «Serial Attributes» desk page.

Lists Serial Nos with their `Additional Attribute Row` values, and applies attribute values
to many serials at once — either the ones ticked in the table or a pasted list of serial
numbers.
"""

import frappe
from frappe import _
from frappe.utils import cint

ROW_DOCTYPE = "Additional Attribute Row"
ROW_FIELDNAME = "additional_attributes"
MAX_ROWS = 2000


def _check_read():
	frappe.has_permission("Serial No", "read", throw=True)


def _check_write():
	frappe.has_permission("Serial No", "write", throw=True)


@frappe.whitelist()
def get_serials(
	item_code=None,
	item_group=None,
	warehouse=None,
	status=None,
	attribute=None,
	value=None,
	missing_only=0,
	in_stock_only=1,
	limit=500,
):
	"""Serial Nos matching the filters, each with its additional attributes.

	`missing_only` flips the `attribute` filter into "serials that have no row for this
	attribute" — the list you then select and fill in.
	"""
	_check_read()

	missing_only = cint(missing_only)
	in_stock_only = cint(in_stock_only)
	limit = min(cint(limit) or 500, MAX_ROWS)

	sn = frappe.qb.DocType("Serial No")
	query = (
		frappe.qb.from_(sn)
		.select(sn.name, sn.item_code, sn.item_name, sn.warehouse, sn.status)
		.orderby(sn.item_code)
		.orderby(sn.name)
		.limit(limit)
	)

	if item_code:
		query = query.where(sn.item_code == item_code)
	if warehouse:
		query = query.where(sn.warehouse == warehouse)
	if status:
		query = query.where(sn.status == status)
	elif in_stock_only:
		query = query.where(sn.warehouse.notnull() & (sn.warehouse != ""))

	if item_group:
		item = frappe.qb.DocType("Item")
		query = query.join(item).on(item.name == sn.item_code).where(item.item_group == item_group)

	if attribute:
		row = frappe.qb.DocType(ROW_DOCTYPE)
		matching = (
			frappe.qb.from_(row)
			.select(row.parent)
			.where((row.parenttype == "Serial No") & (row.attribute == attribute))
		)
		if value:
			matching = matching.where(row.value == value)

		if missing_only:
			query = query.where(sn.name.notin(matching))
		else:
			query = query.where(sn.name.isin(matching))

	serials = query.run(as_dict=True)
	if not serials:
		return {"serials": [], "attributes": _column_attributes(attribute)}

	names = [d.name for d in serials]
	rows = frappe.get_all(
		ROW_DOCTYPE,
		filters={"parenttype": "Serial No", "parent": ("in", names)},
		fields=["parent", "attribute", "value", "notes"],
		order_by="idx",
	)

	value_labels = _value_labels([d.value for d in rows])
	by_serial = {}
	for row in rows:
		by_serial.setdefault(row.parent, {})[row.attribute] = {
			"value": row.value,
			"label": value_labels.get(row.value, row.value),
			"notes": row.notes,
		}

	for serial in serials:
		serial["attributes"] = by_serial.get(serial.name, {})

	return {"serials": serials, "attributes": _column_attributes(attribute)}


def _column_attributes(attribute=None):
	"""Which attributes get a column: the filtered one, or every enabled attribute."""
	if attribute:
		return [attribute]

	return [
		d.name
		for d in frappe.get_all(
			"Additional Attribute", filters={"disabled": 0}, fields=["name"], order_by="attribute_name"
		)
	]


def _value_labels(value_names):
	value_names = [d for d in set(value_names) if d]
	if not value_names:
		return {}

	return {
		d.name: d.value
		for d in frappe.get_all(
			"Additional Attribute Value", filters={"name": ("in", value_names)}, fields=["name", "value"]
		)
	}


@frappe.whitelist()
def parse_serials(text, item_code=None):
	"""Split a pasted blob into known / unknown serial numbers.

	Accepts newlines, commas, semicolons, tabs and spaces as separators.
	"""
	_check_read()

	tokens = []
	for chunk in (text or "").replace(",", "\n").replace(";", "\n").replace("\t", "\n").split("\n"):
		token = chunk.strip()
		if token:
			tokens.append(token)

	# preserve the pasted order, drop repeats
	seen = set()
	ordered = []
	for token in tokens:
		if token not in seen:
			seen.add(token)
			ordered.append(token)

	if not ordered:
		return {"found": [], "unknown": [], "wrong_item": []}

	filters = {"name": ("in", ordered)}
	existing = {
		d.name: d.item_code
		for d in frappe.get_all("Serial No", filters=filters, fields=["name", "item_code"])
	}

	found, unknown, wrong_item = [], [], []
	for token in ordered:
		if token not in existing:
			unknown.append(token)
		elif item_code and existing[token] != item_code:
			wrong_item.append(token)
		else:
			found.append(token)

	return {"found": found, "unknown": unknown, "wrong_item": wrong_item}


@frappe.whitelist()
def set_attribute(serials, attribute, value=None, notes=None, overwrite=1, clear=0):
	"""Set (or clear) one attribute on many Serial Nos.

	`overwrite=0` skips serials that already carry a value for this attribute — the safe mode
	for filling gaps. `clear=1` removes the attribute row instead of setting it.
	"""
	_check_write()

	serials = frappe.parse_json(serials) if isinstance(serials, str) else serials
	serials = [d for d in (serials or []) if d]
	if not serials:
		frappe.throw(_("No serial numbers selected"))

	overwrite = cint(overwrite)
	clear = cint(clear)

	if not attribute:
		frappe.throw(_("Attribute is required"))
	if not clear and not value:
		frappe.throw(_("Value is required"))

	if value:
		value_attribute = frappe.db.get_value("Additional Attribute Value", value, "attribute")
		if not value_attribute:
			frappe.throw(_("Additional Attribute Value {0} does not exist").format(frappe.bold(value)))
		if value_attribute != attribute:
			frappe.throw(
				_("Value {0} belongs to attribute {1}, not {2}").format(
					frappe.bold(value), frappe.bold(value_attribute), frappe.bold(attribute)
				)
			)

	updated, skipped, failed = [], [], []
	for name in serials:
		# one savepoint per serial: a bad row must not undo the serials already written
		save_point = "serial_attributes"
		frappe.db.savepoint(save_point)
		try:
			doc = frappe.get_doc("Serial No", name)
			if not doc.meta.get_field(ROW_FIELDNAME):
				frappe.throw(_("Serial No has no Additional Attributes table"))

			existing = [d for d in doc.get(ROW_FIELDNAME) if d.attribute == attribute]
			if existing and not overwrite and not clear:
				skipped.append(name)
				continue

			for row in existing:
				doc.remove(row)

			if not clear:
				doc.append(ROW_FIELDNAME, {"attribute": attribute, "value": value, "notes": notes})

			doc.save()
			updated.append(name)
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			failed.append({"serial": name, "error": str(e)})

	frappe.db.commit()

	return {"updated": updated, "skipped": skipped, "failed": failed}
