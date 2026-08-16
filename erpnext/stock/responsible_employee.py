"""Responsible Employee — the person a stock item in a shared warehouse belongs to.

The per-person warehouses under "МО" were merged into a single R&D warehouse, so the
custody information now lives on the Responsible Employee inventory dimension instead of
in the warehouse name. Inside the R&D warehouse the dimension is what keeps the balances
apart, so it must not be left empty there.

`Inventory Dimension` cannot enforce that on its own: with `apply_to_all_doctypes` set,
`reset_value()` clears `mandatory_depends_on`. Hence this validator, wired through
`doc_events` in hooks.py.
"""

import frappe
from frappe import _

RESPONSIBLE_EMPLOYEE_DIMENSION = "Responsible Employee"
RESPONSIBLE_EMPLOYEE_FIELD = "responsible_employee"

#: Warehouse the dimension is mandatory for, matched on `warehouse_name` so the company
#: abbreviation does not have to be hardcoded (dev and prod use different ones).
RD_WAREHOUSE_NAME = "R&D"

#: (warehouse fieldname, dimension fieldname) pairs per child doctype. The dimension
#: fieldnames are the ones `InventoryDimension.add_custom_fields()` generates.
WAREHOUSE_DIMENSION_FIELDS = {
	"Stock Entry Detail": (
		("s_warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
		("t_warehouse", f"to_{RESPONSIBLE_EMPLOYEE_FIELD}"),
	),
	"Purchase Receipt Item": (
		("warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
		("rejected_warehouse", f"rejected_{RESPONSIBLE_EMPLOYEE_FIELD}"),
		("from_warehouse", f"from_{RESPONSIBLE_EMPLOYEE_FIELD}"),
	),
	"Purchase Invoice Item": (
		("warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
		("rejected_warehouse", f"rejected_{RESPONSIBLE_EMPLOYEE_FIELD}"),
		("from_warehouse", f"from_{RESPONSIBLE_EMPLOYEE_FIELD}"),
	),
	"Delivery Note Item": (
		("warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
		("target_warehouse", f"to_{RESPONSIBLE_EMPLOYEE_FIELD}"),
	),
	"Sales Invoice Item": (
		("warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
		("target_warehouse", f"to_{RESPONSIBLE_EMPLOYEE_FIELD}"),
	),
	"Stock Reconciliation Item": (("warehouse", RESPONSIBLE_EMPLOYEE_FIELD),),
}


def get_responsible_warehouse(company: str | None) -> str | None:
	"""Name of the warehouse the dimension is mandatory for, or None if it does not exist."""
	if not company:
		return None

	def _resolve():
		return (
			frappe.db.get_value(
				"Warehouse",
				{"warehouse_name": RD_WAREHOUSE_NAME, "company": company},
				"name",
			)
			or ""
		)

	return frappe.cache().hget("responsible_employee_warehouse", company, _resolve) or None


def validate_responsible_employee(doc, method=None):
	"""Require the Responsible Employee dimension on rows touching the R&D warehouse."""
	warehouse = get_responsible_warehouse(doc.get("company"))
	if not warehouse:
		return

	for row in doc.get("items") or []:
		field_pairs = WAREHOUSE_DIMENSION_FIELDS.get(row.doctype)
		if not field_pairs:
			continue

		for warehouse_field, dimension_field in field_pairs:
			if row.get(warehouse_field) != warehouse:
				continue
			if row.get(dimension_field):
				continue
			if not row.meta.has_field(dimension_field):
				continue

			frappe.throw(
				_("Row {0}: {1} is mandatory for warehouse {2}").format(
					row.idx, _(RESPONSIBLE_EMPLOYEE_DIMENSION), frappe.bold(warehouse)
				),
				title=_("Responsible Employee Required"),
			)
