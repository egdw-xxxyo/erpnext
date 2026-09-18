"""Remove the OTDR device identity and the Reflectometer script runtime.

Measurements are scoped by workplace now, not by a per-phone `OTDR` record, and they are
handled by the Workplace Script state machine rather than by a separate Reflectometer
`Device Script` engine. See `erpnext/devices/otdr_measurement_api.py`.

Nothing is migrated forward. The old measurement log was a 100-row FIFO child table of
opaque JSON with no link to a serial number — there is no spool to attach those rows to,
which is the whole reason `OTDR Measurement` exists. `OTDR Configuration` is deliberately
kept: it holds the BLE and sync settings, which did not change.

`Device Script` itself survives — its `Scanner` scripts are the libraries every Workplace
Script calls through the `scripts.*` namespace. Only the Reflectometer rows and the run log
go.
"""

import frappe

DOCTYPES = (
	"OTDR",
	"OTDR QC Item",
	"OTDR Measurement Log Entry",
	"Device Script Run",
)


def execute():
	_delete_reflectometer_scripts()

	for doctype in DOCTYPES:
		_drop_doctype(doctype)


def _delete_reflectometer_scripts():
	"""Drop Device Script rows that were handlers rather than libraries.

	`script_type` is a Select whose `Reflectometer` option is gone, but the stored column
	value is untouched by a schema sync, so the rows have to be removed explicitly.
	"""
	if not frappe.db.table_exists("Device Script"):
		return

	names = frappe.get_all("Device Script", filters={"script_type": "Reflectometer"}, pluck="name")
	for name in names:
		try:
			frappe.delete_doc("Device Script", name, force=True, ignore_permissions=True)
		except Exception:
			frappe.log_error(title=f"Could not delete Reflectometer Device Script {name}")


def _drop_doctype(doctype):
	if not frappe.db.exists("DocType", doctype):
		return

	try:
		frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True, ignore_permissions=True)
	except Exception:
		frappe.log_error(title=f"Could not delete DocType {doctype}")
		return

	table = f"tab{doctype}"
	if frappe.db.table_exists(table):
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table}`")
