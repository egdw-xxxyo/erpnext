"""Put every shipped box into the Packages table of the Delivery Notes that took its serials.

`mark_shipped_packages` marked the boxes and linked the latest document on the box, but the
Delivery Notes themselves never listed their boxes. A box split over two notes goes on both.
"""

import frappe

from erpnext.stock.package_shipping import add_delivery_note_row, outbound_moves


def execute():
	contents = frappe.db.sql(
		"""
		SELECT p.name, pi.serial_no
		FROM `tabPackage` p
		JOIN `tabPackage Item` pi ON pi.parent = p.name AND pi.parenttype = 'Package'
		WHERE p.docstatus = 1 AND p.status = 'Shipped' AND IFNULL(pi.serial_no, '') != ''
		""",
		as_dict=True,
	)
	boxes = {}
	for row in contents:
		boxes.setdefault(row.name, []).append(row.serial_no)
	if not boxes:
		return

	moves = outbound_moves([s for serials in boxes.values() for s in serials])
	added = 0
	for name, serials in boxes.items():
		notes = {}
		for serial in serials:
			move = moves.get(serial)
			if move and move.voucher_type == "Delivery Note":
				notes.setdefault(move.voucher_no, []).append(serial)
		for delivery_note, shipped in notes.items():
			before = frappe.db.count("Delivery Note Package", {"parent": delivery_note, "package": name})
			add_delivery_note_row(delivery_note, name, shipped, "Shipped")
			added += not before
	print(f"Delivery Note package rows added: {added}")
