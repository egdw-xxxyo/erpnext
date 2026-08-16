"""Merge the per-person warehouses under "МО" into a single R&D warehouse.

Each materially responsible person used to own a named warehouse sitting next to
"Склад ARB" and "Ремонтний відділ". They are nearly idle, duplicate the item list and
bloat the warehouse tree, so they collapse into one "R&D" warehouse and the custody
information moves onto the Responsible Employee inventory dimension:

    Warehouse "Воробієвський Дмитро"  ->  Warehouse "R&D", responsible "Дмитро Воробієвський"

Order matters. The dimension is backfilled *before* the merge — afterwards the warehouse
names are gone and "whose item is this" would be lost for good. Bins are dropped before
renaming because `rename_doc` blindly updates every Warehouse link field and Bin has a
unique (item_code, warehouse) index; several items sit in two or three of these
warehouses. Bins and the per-warehouse SLE running totals are rebuilt afterwards by
`repost_stock`, the same helper Item merging uses.
"""

import frappe
from frappe.model.rename_doc import rename_doc

from erpnext.patches.setup_custom_fields import create_responsible_employee_dimension
from erpnext.stock.responsible_employee import RD_WAREHOUSE_NAME, RESPONSIBLE_EMPLOYEE_FIELD

#: Warehouse name (without company abbreviation) -> employee full name. Resolved to the
#: Employee record by name so the patch works on any site that has these warehouses.
WAREHOUSE_TO_EMPLOYEE = {
	"Воробієвський Дмитро": "Дмитро Воробієвський",
	"Копилов Костя": "Костянтин Копилов",
	"Кущ Вячаслав": "Вячеслав Кущ",
	"Міщенко Данило": "Данило Міщенко",
	"Овчаров Роман": "Роман Овчаров",
	"Рижков Олег": "Олег Рижков",
	"Ярош Кирило": "Кирило Ярош",
}

#: Preferred warehouse to rename into R&D; the rest are merged into it. If it is absent,
#: the first of the remaining ones (in the order above) is renamed instead.
RENAME_SOURCE = "Воробієвський Дмитро"

#: (child doctype, warehouse fieldname, dimension fieldname) rows to backfill.
BACKFILL_TARGETS = (
	("Stock Ledger Entry", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Stock Entry Detail", "s_warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Stock Entry Detail", "t_warehouse", f"to_{RESPONSIBLE_EMPLOYEE_FIELD}"),
	("Purchase Receipt Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Purchase Invoice Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Delivery Note Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Sales Invoice Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Stock Reconciliation Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Material Request Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Purchase Order Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
	("Sales Order Item", "warehouse", RESPONSIBLE_EMPLOYEE_FIELD),
)


def execute():
	# deploy runs `bench migrate` before setup_custom_fields, so the dimension this patch
	# writes into does not exist yet on the first deploy — create it here.
	create_responsible_employee_dimension()

	if not frappe.db.has_column("Stock Ledger Entry", RESPONSIBLE_EMPLOYEE_FIELD):
		print("Responsible Employee dimension is missing, skipping")
		return

	for company, abbr in frappe.get_all("Company", fields=["name", "abbr"], as_list=True):
		_merge_for_company(company, abbr)

	frappe.db.commit()


def _merge_for_company(company: str, abbr: str):
	sources = {}
	for warehouse_name, employee_name in WAREHOUSE_TO_EMPLOYEE.items():
		warehouse = frappe.db.get_value(
			"Warehouse", {"warehouse_name": warehouse_name, "company": company}, "name"
		)
		if not warehouse:
			continue

		employee = _find_employee(employee_name, company)
		if not employee:
			print(f"{company}: no Employee named {employee_name} — leaving {warehouse} alone")
			continue

		sources[warehouse_name] = (warehouse, employee)

	if not sources:
		return

	target = frappe.db.get_value(
		"Warehouse", {"warehouse_name": RD_WAREHOUSE_NAME, "company": company}, "name"
	)

	for warehouse, employee in sources.values():
		_backfill_dimension(warehouse, employee)
		frappe.db.delete("Bin", {"warehouse": warehouse})

	if not target:
		rename_source = RENAME_SOURCE if RENAME_SOURCE in sources else next(iter(sources))
		target = _rename_to_rd(sources.pop(rename_source)[0], abbr)

	for warehouse, _employee in sources.values():
		if warehouse == target:
			continue
		print(f"{company}: merging {warehouse} into {target}")
		rename_doc("Warehouse", warehouse, target, merge=True, force=True, ignore_permissions=True)

	_repost(target)


def _find_employee(employee_name: str, company: str) -> str | None:
	"""Employee of this company, or the only site-wide match if the company differs."""
	employee = frappe.db.get_value("Employee", {"employee_name": employee_name, "company": company}, "name")
	if employee:
		return employee

	matches = frappe.get_all("Employee", filters={"employee_name": employee_name}, pluck="name")
	return matches[0] if len(matches) == 1 else None


def _backfill_dimension(warehouse: str, employee: str):
	"""Stamp the responsible employee on everything that still names this warehouse."""
	for doctype, warehouse_field, dimension_field in BACKFILL_TARGETS:
		table = f"tab{doctype}"
		if not frappe.db.table_exists(doctype):
			continue
		if not frappe.db.has_column(doctype, dimension_field):
			continue

		frappe.db.sql(
			f"""update `{table}`
			set `{dimension_field}` = %(employee)s
			where `{warehouse_field}` = %(warehouse)s and ifnull(`{dimension_field}`, '') = ''""",
			{"employee": employee, "warehouse": warehouse},
		)

	print(f"  stamped {employee} on history of {warehouse}")


def _rename_to_rd(warehouse: str, abbr: str) -> str:
	target = f"{RD_WAREHOUSE_NAME} - {abbr}"
	print(f"renaming {warehouse} -> {target}")
	# Warehouse has allow_rename = 0, so the rename needs force.
	rename_doc("Warehouse", warehouse, target, force=True, ignore_permissions=True)
	# Warehouse has no before_rename, so warehouse_name does not follow the name.
	frappe.db.set_value("Warehouse", target, "warehouse_name", RD_WAREHOUSE_NAME, update_modified=False)
	return target


def _repost(warehouse: str):
	"""Rebuild Bins and queue a valuation repost — the merged SLEs carry per-warehouse totals."""
	from erpnext.stock.stock_balance import repost_stock

	items = frappe.get_all(
		"Stock Ledger Entry",
		filters={"warehouse": warehouse, "is_cancelled": 0},
		pluck="item_code",
		distinct=True,
	)
	if not items:
		return

	allow_negative_stock = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	try:
		for item_code in items:
			repost_stock(item_code, warehouse)
	finally:
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", allow_negative_stock)

	print(f"  queued repost for {len(items)} items in {warehouse}")
