import frappe
from frappe import _
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils.nestedset import get_descendants_of
from pypika.terms import ExistsCriterion


def execute(filters=None):
	if not filters:
		filters = frappe._dict()

	mode = filters.get("mode", "By Item Groups")

	if mode == "By Product BOM":
		columns = get_columns(filters, bom_mode=True)
		data = get_bom_data(filters)
	else:
		columns = get_columns(filters, bom_mode=False)
		data = get_group_data(filters)

	return columns, data


def get_columns(filters, bom_mode=False):
	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 250},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 350},
		{"fieldname": "item_group", "label": _("Item Group"), "fieldtype": "Link", "options": "Item Group", "width": 200},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 80},
		{"fieldname": "actual_qty", "label": _("In Stock Qty"), "fieldtype": "Float", "width": 150},
	]

	if bom_mode:
		columns.extend([
			{"fieldname": "required_qty", "label": _("Required Qty"), "fieldtype": "Float", "width": 120},
			{"fieldname": "difference_qty", "label": _("Difference"), "fieldtype": "Float", "width": 120},
		])

	if filters.get("show_value"):
		columns.extend([
			{"fieldname": "stock_value", "label": _("Stock Value"), "fieldtype": "Currency", "width": 120},
			{"fieldname": "valuation_rate", "label": _("Valuation Rate"), "fieldtype": "Currency", "width": 120},
		])

	return columns


def get_warehouse_condition(query, bin_table, filters):
	warehouse = filters.get("warehouse")
	if not warehouse:
		return query

	warehouse_details = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=1)
	if warehouse_details:
		wh = frappe.qb.DocType("Warehouse")
		query = query.where(
			ExistsCriterion(
				frappe.qb.from_(wh)
				.select(wh.name)
				.where(
					(wh.lft >= warehouse_details.lft)
					& (wh.rgt <= warehouse_details.rgt)
					& (bin_table.warehouse == wh.name)
				)
			)
		)
	else:
		query = query.where(bin_table.warehouse == warehouse)

	return query


def get_group_data(filters):
	item_groups = filters.get("item_groups") or []
	if not item_groups:
		return []

	all_groups = set()
	for group in item_groups:
		all_groups.add(group)
		if filters.get("include_subgroups"):
			all_groups.update(get_descendants_of("Item Group", group))

	item = frappe.qb.DocType("Item")
	bin_table = frappe.qb.DocType("Bin")

	query = (
		frappe.qb.from_(bin_table)
		.inner_join(item)
		.on(bin_table.item_code == item.name)
		.select(
			item.name.as_("item_code"),
			item.item_name,
			item.item_group,
			item.stock_uom,
			Sum(bin_table.actual_qty).as_("actual_qty"),
			Sum(bin_table.stock_value).as_("stock_value"),
			bin_table.valuation_rate,
		)
		.where(item.item_group.isin(list(all_groups)))
		.where(item.is_stock_item == 1)
		.groupby(item.name)
		.orderby(item.item_group)
		.orderby(item.item_name)
	)

	if filters.get("company"):
		wh = frappe.qb.DocType("Warehouse")
		query = query.where(
			ExistsCriterion(
				frappe.qb.from_(wh)
				.select(wh.name)
				.where((wh.company == filters.get("company")) & (bin_table.warehouse == wh.name))
			)
		)

	query = get_warehouse_condition(query, bin_table, filters)

	return query.run(as_dict=True)


def get_bom_data(filters):
	bom = filters.get("bom")
	if not bom:
		return []

	qty_to_produce = filters.get("qty_to_produce") or 1

	bom_item = frappe.qb.DocType("BOM Explosion Item")
	item = frappe.qb.DocType("Item")
	bin_table = frappe.qb.DocType("Bin")

	query = (
		frappe.qb.from_(bom_item)
		.inner_join(item)
		.on(bom_item.item_code == item.name)
		.left_join(bin_table)
		.on(bom_item.item_code == bin_table.item_code)
		.select(
			bom_item.item_code,
			item.item_name,
			item.item_group,
			item.stock_uom,
			bom_item.qty_consumed_per_unit,
			IfNull(Sum(bin_table.actual_qty), 0).as_("actual_qty"),
			IfNull(Sum(bin_table.stock_value), 0).as_("stock_value"),
			bin_table.valuation_rate,
		)
		.where((bom_item.parent == bom) & (bom_item.parenttype == "BOM"))
		.groupby(bom_item.item_code)
		.orderby(item.item_group)
		.orderby(item.item_name)
	)

	query = get_warehouse_condition(query, bin_table, filters)

	data = query.run(as_dict=True)

	for row in data:
		row.required_qty = (row.qty_consumed_per_unit or 0) * qty_to_produce
		row.difference_qty = (row.actual_qty or 0) - row.required_qty

	return data
