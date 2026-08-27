import frappe
from frappe import _
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import flt
from frappe.utils.nestedset import get_descendants_of
from pypika.terms import ExistsCriterion

from erpnext.stock.responsible_employee import RESPONSIBLE_EMPLOYEE_FIELD


def execute(filters=None):
	if not filters:
		filters = frappe._dict()

	filters = frappe._dict(filters)
	mode = filters.get("mode", "By Item Groups")
	bom_mode = mode == "By Product BOM"
	by_employee = is_employee_wise(filters)

	items = get_bom_items(filters) if bom_mode else get_group_items(filters)
	data = attach_balances(items, filters, by_employee)

	if bom_mode:
		apply_bom_requirements(data, filters)

	return get_columns(filters, bom_mode=bom_mode, by_employee=by_employee), data


def is_employee_wise(filters):
	"""Whether the balance has to be split per Responsible Employee.

	The dimension only exists once the `Responsible Employee` Inventory Dimension has been
	created, and it lives on Stock Ledger Entry — `tabBin` has no such column, so splitting
	by it means giving up the cheap Bin lookup.
	"""
	if not frappe.db.has_column("Stock Ledger Entry", RESPONSIBLE_EMPLOYEE_FIELD):
		return False

	return bool(filters.get("show_responsible_employee") or filters.get(RESPONSIBLE_EMPLOYEE_FIELD))


def get_columns(filters, bom_mode=False, by_employee=False):
	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 250},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 300},
		{
			"fieldname": "item_group",
			"label": _("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 200,
		},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 80},
	]

	if by_employee:
		columns.append(
			{
				"fieldname": RESPONSIBLE_EMPLOYEE_FIELD,
				"label": _("Responsible Employee"),
				"fieldtype": "Link",
				"options": "Employee",
				"width": 200,
			}
		)

	columns.append(
		{"fieldname": "actual_qty", "label": _("In Stock Qty"), "fieldtype": "Float", "width": 180}
	)

	if by_employee:
		columns.append(
			{
				"fieldname": "total_actual_qty",
				"label": _("Total In Stock Qty"),
				"fieldtype": "Float",
				"width": 150,
			}
		)

	if bom_mode:
		columns.extend(
			[
				{"fieldname": "required_qty", "label": _("Required Qty"), "fieldtype": "Float", "width": 120},
				{"fieldname": "difference_qty", "label": _("Difference"), "fieldtype": "Float", "width": 120},
			]
		)

	if filters.get("show_value"):
		columns.extend(
			[
				{
					"fieldname": "stock_value",
					"label": _("Stock Value"),
					"fieldtype": "Currency",
					"width": 120,
				},
				{
					"fieldname": "valuation_rate",
					"label": _("Valuation Rate"),
					"fieldtype": "Currency",
					"width": 120,
				},
			]
		)

	return columns


def get_group_items(filters):
	item_groups = filters.get("item_groups") or []
	if not item_groups:
		return []

	all_groups = set()
	for group in item_groups:
		all_groups.add(group)
		if filters.get("include_subgroups"):
			all_groups.update(get_descendants_of("Item Group", group))

	item = frappe.qb.DocType("Item")

	return (
		frappe.qb.from_(item)
		.select(item.name.as_("item_code"), item.item_name, item.item_group, item.stock_uom)
		.where(item.item_group.isin(list(all_groups)))
		.where(item.is_stock_item == 1)
		.orderby(item.item_group)
		.orderby(item.item_name)
		.run(as_dict=True)
	)


def get_bom_items(filters):
	bom = filters.get("bom")
	if not bom:
		return []

	bom_item = frappe.qb.DocType("BOM Explosion Item")
	item = frappe.qb.DocType("Item")

	return (
		frappe.qb.from_(bom_item)
		.inner_join(item)
		.on(bom_item.item_code == item.name)
		.select(
			bom_item.item_code,
			item.item_name,
			item.item_group,
			item.stock_uom,
			Sum(bom_item.qty_consumed_per_unit).as_("qty_consumed_per_unit"),
		)
		.where((bom_item.parent == bom) & (bom_item.parenttype == "BOM"))
		.groupby(bom_item.item_code)
		.orderby(item.item_group)
		.orderby(item.item_name)
		.run(as_dict=True)
	)


def apply_warehouse_scope(query, table, filters, has_company_column=False):
	"""Restrict a Bin / Stock Ledger Entry query to the filtered company and warehouse tree."""
	if filters.get("company"):
		if has_company_column:
			query = query.where(table.company == filters.get("company"))
		else:
			wh = frappe.qb.DocType("Warehouse")
			query = query.where(
				ExistsCriterion(
					frappe.qb.from_(wh)
					.select(wh.name)
					.where((wh.company == filters.get("company")) & (wh.name == table.warehouse))
				)
			)

	warehouse = filters.get("warehouse")
	if warehouse:
		warehouse_details = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=1)
		if warehouse_details:
			wh2 = frappe.qb.DocType("Warehouse")
			query = query.where(
				ExistsCriterion(
					frappe.qb.from_(wh2)
					.select(wh2.name)
					.where(
						(wh2.lft >= warehouse_details.lft)
						& (wh2.rgt <= warehouse_details.rgt)
						& (wh2.name == table.warehouse)
					)
				)
			)
		else:
			query = query.where(table.warehouse == warehouse)

	return query


def get_bin_balances(filters, item_codes):
	"""{item_code: {None: balance}} — the cheap path, one row per item."""
	bin_table = frappe.qb.DocType("Bin")

	query = (
		frappe.qb.from_(bin_table)
		.select(
			bin_table.item_code,
			IfNull(Sum(bin_table.actual_qty), 0).as_("actual_qty"),
			IfNull(Sum(bin_table.stock_value), 0).as_("stock_value"),
		)
		.where(bin_table.item_code.isin(item_codes))
		.groupby(bin_table.item_code)
	)
	query = apply_warehouse_scope(query, bin_table, filters)

	balances = {}
	for row in query.run(as_dict=True):
		balances[row.item_code] = {None: make_balance(row.actual_qty, row.stock_value)}

	return balances


def get_sle_balances(filters, item_codes):
	"""{item_code: {employee: balance}} — summed from the ledger, the only place the dimension lives."""
	sle = frappe.qb.DocType("Stock Ledger Entry")
	employee_field = sle[RESPONSIBLE_EMPLOYEE_FIELD]

	query = (
		frappe.qb.from_(sle)
		.select(
			sle.item_code,
			employee_field,
			Sum(sle.actual_qty).as_("actual_qty"),
			Sum(sle.stock_value_difference).as_("stock_value"),
		)
		.where(sle.item_code.isin(item_codes))
		.where((sle.is_cancelled == 0) & (sle.docstatus < 2))
		.groupby(sle.item_code, employee_field)
	)
	query = apply_warehouse_scope(query, sle, filters, has_company_column=True)

	selected_employees = filters.get(RESPONSIBLE_EMPLOYEE_FIELD)
	if selected_employees:
		query = query.where(employee_field.isin(selected_employees))

	balances = {}
	for row in query.run(as_dict=True):
		employee = row.get(RESPONSIBLE_EMPLOYEE_FIELD) or None
		balances.setdefault(row.item_code, {})[employee] = make_balance(row.actual_qty, row.stock_value)

	return balances


def make_balance(actual_qty, stock_value):
	qty = flt(actual_qty)
	value = flt(stock_value)

	return {
		"actual_qty": qty,
		"stock_value": value,
		"valuation_rate": value / qty if qty else 0,
	}


def attach_balances(items, filters, by_employee):
	"""Expand every item into one row per balance bucket (per employee, or a single one)."""
	if not items:
		return []

	item_codes = [row.item_code for row in items]
	balances = get_sle_balances(filters, item_codes) if by_employee else get_bin_balances(filters, item_codes)

	data = []
	for item in items:
		buckets = balances.get(item.item_code) or {None: make_balance(0, 0)}
		item_total = sum(flt(bucket["actual_qty"]) for bucket in buckets.values())

		employees = sorted(buckets, key=lambda name: name or "")
		if not filters.get("show_zero_qty"):
			# dropped here rather than on the finished rows, so that the per-item numbers
			# never land on a bucket that is about to disappear
			employees = [name for name in employees if flt(buckets[name]["actual_qty"])]

		for idx, employee in enumerate(employees):
			bucket = buckets[employee]
			row = item.copy()
			row[RESPONSIBLE_EMPLOYEE_FIELD] = employee
			row.actual_qty = bucket["actual_qty"]
			row.stock_value = bucket["stock_value"]
			row.valuation_rate = bucket["valuation_rate"]
			# the item total is repeated on every bucket for the client-side colouring, but
			# only shown (and hence added into the total row) on the item's first bucket
			row._total_qty = item_total
			row.total_actual_qty = item_total if idx == 0 else None
			row.is_first_bucket = idx == 0
			data.append(row)

	return data


def apply_bom_requirements(data, filters):
	"""Requirement is per item, so it is written on the item's first bucket only."""
	qty_to_produce = flt(filters.get("qty_to_produce")) or 1

	for row in data:
		required_qty = flt(row.get("qty_consumed_per_unit")) * qty_to_produce
		row._required_qty = required_qty
		row.required_qty = required_qty if row.get("is_first_bucket") else None
		row.difference_qty = flt(row.get("_total_qty")) - required_qty if row.get("is_first_bucket") else None
