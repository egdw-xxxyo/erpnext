"""A serial number ships only after the receipt that brings it in is posted.

A draft Purchase Receipt already creates its Serial Nos as Active in the target warehouse, and the
stock check of an outbound document trusts that warehouse. So a unit can leave on a Delivery Note
before its receipt is submitted; the receipt posted later puts it back into stock on paper. Both
hooks here compare the posted movements of each serial instead.
"""

import frappe
from frappe import _

from erpnext.manufacturing.packing import delivered_serials
from erpnext.stock.package_shipping import direction
from erpnext.stock.utils import get_combine_datetime


def _posting_datetime(doc):
	return get_combine_datetime(doc.posting_date, doc.posting_time or "00:00:00")


def net_movements(serials, until, exclude_voucher=None):
	"""`{serial: inward - outward}` over posted bundles up to `until`; a serial never moved is absent."""
	if not serials:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT sbe.serial_no,
			SUM(CASE sbb.type_of_transaction WHEN 'Inward' THEN 1 WHEN 'Outward' THEN -1 ELSE 0 END) AS net
		FROM `tabSerial and Batch Entry` sbe
		JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
		WHERE sbe.serial_no IN %(serials)s
		  AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
		  AND sbb.posting_datetime <= %(until)s
		  AND sbb.voucher_no != %(exclude)s
		GROUP BY sbe.serial_no
		""",
		{"serials": list(serials), "until": until, "exclude": exclude_voucher or ""},
		as_dict=True,
	)
	return {row.serial_no: int(row.net or 0) for row in rows}


def _draft_receipts(serials):
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT sbb.voucher_no
		FROM `tabSerial and Batch Entry` sbe
		JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
		WHERE sbe.serial_no IN %(serials)s
		  AND sbb.docstatus = 0 AND sbb.type_of_transaction = 'Inward'
		""",
		{"serials": list(serials)},
	)


def block_unreceived(doc, method=None):
	"""`doc_events` before_submit on outbound documents: every serial must be in stock by its posted moves."""
	if direction(doc) != "out":
		return
	serials = delivered_serials(doc)
	if not serials:
		return
	net = net_movements(serials, _posting_datetime(doc), exclude_voucher=doc.name)
	missing = sorted(s for s in serials if net.get(s, 0) < 1)
	if not missing:
		return
	message = _("Serial numbers are not received yet on {0}: {1}").format(
		frappe.format(doc.posting_date, {"fieldtype": "Date"}), ", ".join(missing)
	)
	drafts = _draft_receipts(missing)
	if drafts:
		message += "<br>" + _("Submit the receipt first: {0}").format(", ".join(drafts))
	frappe.throw(message, title=_("Serial numbers not in stock"))


def block_receipt_after_shipment(doc, method=None):
	"""`doc_events` before_submit on Purchase Receipt: not posted later than a shipment of its serials."""
	if doc.get("is_return"):
		return
	serials = delivered_serials(doc)
	if not serials:
		return
	net = net_movements(serials, _posting_datetime(doc), exclude_voucher=doc.name)
	shipped = sorted(s for s, n in net.items() if n < 0)
	if not shipped:
		return
	vouchers = frappe.db.sql(
		"""
		SELECT sbb.voucher_no, MIN(sbb.posting_datetime) AS posted
		FROM `tabSerial and Batch Entry` sbe
		JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
		WHERE sbe.serial_no IN %(serials)s
		  AND sbb.docstatus = 1 AND sbb.is_cancelled = 0 AND sbb.type_of_transaction = 'Outward'
		GROUP BY sbb.voucher_no
		ORDER BY posted
		""",
		{"serials": shipped},
		as_dict=True,
	)
	frappe.throw(
		_(
			"Serial numbers {0} already left stock before this receipt: {1}. Set the posting date of the"
			" receipt before {2}"
		).format(
			", ".join(shipped),
			", ".join(v.voucher_no for v in vouchers),
			frappe.format(vouchers[0].posted, {"fieldtype": "Datetime"}) if vouchers else "-",
		),
		title=_("Receipt posted after shipment"),
	)
