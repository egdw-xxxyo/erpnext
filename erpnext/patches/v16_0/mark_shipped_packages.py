"""Mark as Shipped every packed box whose serials all already left stock.

Boxes were never marked when their serials were delivered, so they all stayed `Packed`. A serial
counts as gone when an outbound document (see `erpnext.stock.package_shipping`) took it out and it
is not back in a warehouse; the box links the latest such document. A box gone only in part stays
`Packed` and is listed in an Error Log for a manual fix.
"""

import frappe

from erpnext.stock.package_shipping import ISSUE_PURPOSES, LINK_FIELD, after_status_change


def execute():
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
		  AND sbe.serial_no IN (
			SELECT pi.serial_no FROM `tabPackage Item` pi
			JOIN `tabPackage` p ON p.name = pi.parent
			WHERE pi.parenttype = 'Package' AND p.docstatus = 1 AND p.status = 'Packed'
		  )
		  AND (
			(dn.docstatus = 1 AND dn.is_return = 0)
			OR (si.docstatus = 1 AND si.update_stock = 1 AND si.is_return = 0)
			OR (se.docstatus = 1 AND se.purpose IN %(purposes)s)
		  )
		""",
		{"purposes": ISSUE_PURPOSES},
		as_dict=True,
	)
	gone = {}
	for row in rows:
		if row.serial_no not in gone or row.posting_datetime > gone[row.serial_no].posting_datetime:
			gone[row.serial_no] = row
	if not gone:
		return

	contents = frappe.db.sql(
		"""
		SELECT p.name, pi.serial_no
		FROM `tabPackage` p
		JOIN `tabPackage Item` pi ON pi.parent = p.name AND pi.parenttype = 'Package'
		WHERE p.docstatus = 1 AND p.status = 'Packed' AND IFNULL(pi.serial_no, '') != ''
		""",
		as_dict=True,
	)
	boxes = {}
	for row in contents:
		boxes.setdefault(row.name, []).append(row.serial_no)

	shipped, partial = [], []
	for name, serials in boxes.items():
		moves = [gone[s] for s in serials if s in gone]
		if not moves:
			continue
		if len(moves) < len(serials):
			partial.append(
				f"{name}: {len(moves)}/{len(serials)} ({', '.join(sorted({m.voucher_no for m in moves}))})"
			)
			continue
		links = {}
		for move in sorted(moves, key=lambda m: m.posting_datetime):
			links[LINK_FIELD[move.voucher_type]] = move.voucher_no
		frappe.db.set_value("Package", name, {"status": "Shipped", **links}, update_modified=False)
		shipped.append(name)

	if shipped:
		after_status_change(shipped)
	if partial:
		frappe.log_error(title="Package partially shipped", message="\n".join(partial))
	print(f"Packages marked Shipped: {len(shipped)}; partially shipped, left Packed: {len(partial)}")
