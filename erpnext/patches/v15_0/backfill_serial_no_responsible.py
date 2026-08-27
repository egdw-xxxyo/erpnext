"""Fill the new `Serial No.responsible_employee` from the ledger.

The field is written going forward by `erpnext.stock.responsible_employee.set_serial_no_responsible`
on every submitted Stock Ledger Entry, but serials that moved before it existed carry
nothing. Their holder is the responsible employee of the last inward ledger entry that
moved them — the same entry stock used to set `Serial No.warehouse`, so the two stay
consistent.

Only serials that are currently in a warehouse are touched: one that has left (warehouse
cleared) is held by nobody.

Limitation: entries that recorded serials in the legacy `Stock Ledger Entry.serial_no`
text column are not matched — the dimension is newer than the move to Serial and Batch
Bundles, so no ledger row can have both.
"""

import frappe
from frappe.utils import cint

from erpnext.patches.setup_custom_fields import create_serial_no_responsible_field
from erpnext.stock.responsible_employee import RESPONSIBLE_EMPLOYEE_FIELD


def execute():
	# deploy runs `bench migrate` before setup_custom_fields, so on the first deploy the
	# column this patch writes into does not exist yet
	create_serial_no_responsible_field()

	if not frappe.db.has_column("Stock Ledger Entry", RESPONSIBLE_EMPLOYEE_FIELD):
		return

	frappe.db.sql(
		f"""
		UPDATE `tabSerial No` sn
		INNER JOIN (
			SELECT serial_no, {RESPONSIBLE_EMPLOYEE_FIELD} AS employee
			FROM (
				SELECT
					sbe.serial_no AS serial_no,
					sle.{RESPONSIBLE_EMPLOYEE_FIELD},
					ROW_NUMBER() OVER (
						PARTITION BY sbe.serial_no
						ORDER BY sle.posting_datetime DESC, sle.creation DESC
					) AS rn
				FROM `tabStock Ledger Entry` sle
				INNER JOIN `tabSerial and Batch Entry` sbe
					ON sbe.parent = sle.serial_and_batch_bundle
				WHERE sle.is_cancelled = 0
					AND sle.docstatus = 1
					AND sle.actual_qty > 0
					AND sbe.docstatus = 1
			) ranked
			WHERE rn = 1
		) latest ON latest.serial_no = sn.name
		SET sn.{RESPONSIBLE_EMPLOYEE_FIELD} = latest.employee
		WHERE sn.warehouse IS NOT NULL
			AND sn.warehouse != ''
			AND (sn.{RESPONSIBLE_EMPLOYEE_FIELD} IS NULL OR sn.{RESPONSIBLE_EMPLOYEE_FIELD} = '')
			AND latest.employee IS NOT NULL
		"""
	)

	updated = cint(frappe.db._cursor.rowcount)
	frappe.db.commit()
	print(f"  Backfilled Serial No responsible employee: {updated} rows")
