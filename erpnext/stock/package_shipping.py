"""A packed box leaves stock whole, and the document that takes it out marks it Shipped.

A serial that sits in a submitted `Package` with status `Packed` can be shipped, invoiced with stock or
issued only together with every other serial of that box. Submitting the document marks the box
`Shipped` and links it; cancelling it, or returning the whole box, puts the box back to `Packed`.
"""

import frappe
from frappe import _

from erpnext.manufacturing.packing import delivered_serials

LINK_FIELD = {
	"Delivery Note": "delivery_note",
	"Sales Invoice": "sales_invoice",
	"Stock Entry": "stock_entry",
}
ISSUE_PURPOSES = ("Material Issue", "Send to Subcontractor", "Subcontracting Delivery")


def direction(doc):
	"""`out` for a document that takes stock out, `return` for one that brings it back, else `None`."""
	if doc.doctype == "Stock Entry":
		return "out" if doc.purpose in ISSUE_PURPOSES else None
	if doc.doctype == "Sales Invoice" and not doc.update_stock:
		return None
	return "return" if doc.get("is_return") else "out"


def boxes_with(serials, status):
	"""`{package: {"serials": [...], links}}` for every box in `status` holding any of `serials`."""
	if not serials:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT p.name, p.delivery_note, p.sales_invoice, p.stock_entry, pi.serial_no
		FROM `tabPackage` p
		JOIN `tabPackage Item` pi ON pi.parent = p.name AND pi.parenttype = 'Package'
		WHERE p.docstatus = 1 AND p.status = %(status)s
		  AND pi.serial_no IS NOT NULL AND pi.serial_no != ''
		  AND p.name IN (
			SELECT parent FROM `tabPackage Item`
			WHERE parenttype = 'Package' AND serial_no IN %(serials)s
		  )
		ORDER BY p.name, pi.idx
		""",
		{"status": status, "serials": list(serials)},
		as_dict=True,
	)
	boxes = {}
	for row in rows:
		box = boxes.setdefault(
			row.name,
			frappe._dict(
				serials=[],
				delivery_note=row.delivery_note,
				sales_invoice=row.sales_invoice,
				stock_entry=row.stock_entry,
			),
		)
		box.serials.append(row.serial_no)
	return boxes


def _shipped_by(box):
	return box.delivery_note or box.sales_invoice or box.stock_entry or "-"


def validate_whole_packages(doc, method=None):
	"""`doc_events` validate hook: refuse a part of a box. A draft only gets a warning."""
	way = direction(doc)
	if not way:
		return
	serials = delivered_serials(doc)
	problems = []

	boxes = boxes_with(serials, "Packed" if way == "out" else "Shipped")
	for name, box in boxes.items():
		missing = [s for s in box.serials if s not in serials]
		if missing:
			problems.append(
				_("Package {0}: only the whole package can be moved. Missing serial numbers: {1}").format(
					name, ", ".join(missing)
				)
			)

	if way == "out":
		for name, box in boxes_with(serials, "Shipped").items():
			problems.append(_("Package {0} is already shipped by {1}").format(name, _shipped_by(box)))
		problems += _sync_package_rows(doc, boxes, serials)

	if not problems:
		return
	if doc.docstatus == 1:
		frappe.throw("<br>".join(problems), title=_("Packages must be shipped whole"))
	frappe.msgprint("<br>".join(problems), title=_("Packages must be shipped whole"), indicator="orange")


def _sync_package_rows(doc, boxes, serials):
	"""Fill the Delivery Note `packages` table with every box it ships; a listed box must be complete."""
	if not doc.meta.has_field("packages"):
		return []
	problems = []
	listed = {row.package for row in doc.packages if row.package}
	for name, box in boxes.items():
		if name not in listed:
			doc.append(
				"packages", {"package": name, "serial_nos": "\n".join(box.serials), "status": "Packed"}
			)
	stale = []
	for row in doc.packages:
		if not row.package or row.package in boxes:
			continue
		contents = frappe.get_all(
			"Package Item",
			filters={"parent": row.package, "parenttype": "Package", "serial_no": ["is", "set"]},
			pluck="serial_no",
		)
		if contents and not any(s in serials for s in contents):
			stale.append(row)
			continue
		missing = [s for s in contents if s not in serials]
		if missing:
			problems.append(
				_("Package {0}: add its items. Missing serial numbers: {1}").format(
					row.package, ", ".join(missing)
				)
			)
	# A box whose serials were all taken out of the document no longer ships with it.
	for row in stale:
		doc.remove(row)
	return problems


def mark_shipped(doc, method=None):
	"""`doc_events` on_submit hook: the boxes this document moves change status."""
	way = direction(doc)
	if not way:
		return
	serials = delivered_serials(doc)
	field = LINK_FIELD[doc.doctype]
	if way == "out":
		boxes = _whole(boxes_with(serials, "Packed"), serials)
		_set(boxes, "Shipped", {field: doc.name})
	else:
		boxes = _whole(boxes_with(serials, "Shipped"), serials)
		_set(boxes, "Packed", dict.fromkeys(LINK_FIELD.values()))


def revert_shipped(doc, method=None):
	"""`doc_events` on_cancel hook: undo what `mark_shipped` did."""
	way = direction(doc)
	if not way:
		return
	field = LINK_FIELD[doc.doctype]
	if way == "out":
		boxes = frappe.get_all(
			"Package", filters={field: doc.name, "status": "Shipped", "docstatus": 1}, pluck="name"
		)
		_set(boxes, "Packed", {field: None})
	else:
		serials = delivered_serials(doc)
		boxes = _whole(boxes_with(serials, "Packed"), serials)
		_set(boxes, "Shipped", {field: doc.return_against})


def _whole(boxes, serials):
	return [name for name, box in boxes.items() if all(s in serials for s in box.serials)]


def _set(packages, status, links):
	if not packages:
		return
	for name in packages:
		frappe.db.set_value("Package", name, {"status": status, **links})
	after_status_change(packages)


def after_status_change(packages):
	"""Carry a box status change to the rows and documents that show it."""
	frappe.db.sql(
		"""UPDATE `tabDelivery Note Package` dnp
		   JOIN `tabPackage` p ON p.name = dnp.package
		   SET dnp.status = p.status
		   WHERE dnp.package IN %s""",
		[list(packages)],
	)
	parents = frappe.get_all(
		"Package",
		filters={"name": ["in", list(packages)]},
		fields=["bpak", "pallet", "sales_order"],
	)

	from erpnext.selling.doctype.sales_order.progress import update_so_progress
	from erpnext.stock.doctype.bpak.bpak import update_status_from_package
	from erpnext.stock.doctype.pallet.pallet import update_status_from_packages

	for pallet in {p.pallet for p in parents if p.pallet}:
		update_status_from_packages(pallet)
	for bpak in {p.bpak for p in parents if p.bpak}:
		update_status_from_package(bpak)
	for sales_order in {p.sales_order for p in parents if p.sales_order}:
		update_so_progress(sales_order)


def outbound_moves(serials):
	"""`{serial: latest move}` for serials that an outbound document took out and are not back in stock."""
	if not serials:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT sbe.serial_no, sbb.voucher_type, sbb.voucher_no, sbb.posting_datetime
		FROM `tabSerial and Batch Bundle` sbb
		JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sbb.name
		JOIN `tabSerial No` sn ON sn.name = sbe.serial_no
		LEFT JOIN `tabDelivery Note` dn
			ON sbb.voucher_type = 'Delivery Note' AND dn.name = sbb.voucher_no
		LEFT JOIN `tabSales Invoice` si
			ON sbb.voucher_type = 'Sales Invoice' AND si.name = sbb.voucher_no
		LEFT JOIN `tabStock Entry` se
			ON sbb.voucher_type = 'Stock Entry' AND se.name = sbb.voucher_no
		WHERE sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbb.type_of_transaction = 'Outward'
		  AND IFNULL(sn.warehouse, '') = ''
		  AND sbe.serial_no IN %(serials)s
		  AND (
			(dn.docstatus = 1 AND dn.is_return = 0)
			OR (si.docstatus = 1 AND si.update_stock = 1 AND si.is_return = 0)
			OR (se.docstatus = 1 AND se.purpose IN %(purposes)s)
		  )
		""",
		{"serials": list(serials), "purposes": ISSUE_PURPOSES},
		as_dict=True,
	)
	latest = {}
	for row in rows:
		if row.serial_no not in latest or row.posting_datetime > latest[row.serial_no].posting_datetime:
			latest[row.serial_no] = row
	return latest


def add_delivery_note_row(delivery_note, package, serials, status):
	"""Put a box into the `packages` table of a submitted Delivery Note, once."""
	if frappe.db.exists(
		"Delivery Note Package", {"parent": delivery_note, "parenttype": "Delivery Note", "package": package}
	):
		return
	idx = frappe.db.sql(
		"""SELECT COALESCE(MAX(idx), 0) FROM `tabDelivery Note Package`
		   WHERE parent = %s AND parenttype = 'Delivery Note' AND parentfield = 'packages'""",
		delivery_note,
	)[0][0]
	frappe.get_doc(
		{
			"doctype": "Delivery Note Package",
			"parent": delivery_note,
			"parenttype": "Delivery Note",
			"parentfield": "packages",
			"idx": idx + 1,
			"package": package,
			"box_template": frappe.db.get_value("Package", package, "box_template"),
			"serial_nos": "\n".join(serials),
			"status": status,
		}
	).db_insert()


def link_shipped(package, serials):
	"""A box packed from serials that already left: mark it Shipped and put it on the documents that took them.

	Returns the documents, or nothing when not every serial left (the box then stays Packed).
	"""
	moves = outbound_moves(serials)
	if not serials or len(moves) < len(serials):
		return []
	links = {}
	for move in sorted(moves.values(), key=lambda m: m.posting_datetime):
		links[LINK_FIELD[move.voucher_type]] = move.voucher_no
	frappe.db.set_value("Package", package, {"status": "Shipped", **links})
	notes = sorted({m.voucher_no for m in moves.values() if m.voucher_type == "Delivery Note"})
	for dn in notes:
		add_delivery_note_row(dn, package, [s for s in serials if moves[s].voucher_no == dn], "Shipped")
	return sorted({m.voucher_no for m in moves.values()})


def link_shipped_on_submit(doc):
	"""Called from `Package.on_submit`: a box packed after its serials were shipped is shipped too."""
	serials = [row.serial_no for row in doc.items if row.serial_no]
	docs = link_shipped(doc.name, serials)
	if docs:
		frappe.msgprint(
			_(
				"All serial numbers of package {0} are already shipped by {1}: the package is marked Shipped"
			).format(doc.name, ", ".join(docs)),
			indicator="blue",
			alert=True,
		)
	return docs


@frappe.whitelist()
def package_contents(package):
	"""Scan data of a packed box, for adding the whole box to a document."""
	from erpnext.stock.utils import package_scan_data

	frappe.has_permission("Package", "read", package, throw=True)
	status = frappe.db.get_value("Package", package, "status")
	if status != "Packed":
		frappe.throw(_("Package {0} is {1}: only a packed package can be shipped").format(package, _(status)))
	return package_scan_data(package)


@frappe.whitelist()
def package_of_serial(serial_no):
	"""Scan data of the packed box holding `serial_no` when the box holds more than that one serial."""
	from erpnext.stock.utils import package_scan_data

	frappe.has_permission("Package", "read", throw=True)
	boxes = boxes_with([serial_no], "Packed")
	name = next((name for name, box in boxes.items() if len(box.serials) > 1), None)
	return package_scan_data(name) if name else None
