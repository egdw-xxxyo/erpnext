from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.buying.procurement_automation import require_buyer_role

REPEAT_ITEM_FIELDS = (
	"supplier",
	"related_supplier",
	"item_code",
	"item_name",
	"description",
	"qty",
	"uom",
	"rate",
	"warehouse",
	"project",
)


def _stock_factor(item_code, uom, source):
	if uom == source.uom:
		return flt(source.conversion_factor) or 1
	from erpnext.stock.get_item_details import get_conversion_factor

	factor = flt(get_conversion_factor(item_code, uom).get("conversion_factor"))
	if factor <= 0:
		frappe.throw(_("No conversion factor is configured for item {0} and UOM {1}.").format(item_code, uom))
	return factor


def get_material_request_remaining(source, exclude=None, lock=False):
	"""Reserve quantities by original row, including drafts and excluding rejected/cancelled orders."""
	source_items = {row.name: row for row in source.items}
	# A locking read observes the latest reservations even if this transaction already
	# read an older version before acquiring the Material Request lock.
	rows = frappe.db.sql(
		"""select i.parent, i.material_request_item, i.item_code, i.uom, i.qty, i.purchase_order_item
		from `tabConsolidated Purchase Order Item` i
		inner join `tabConsolidated Purchase Order` p on p.name = i.parent
		where i.material_request = %(source)s and p.docstatus < 2
		and coalesce(p.workflow_state, '') != 'Відхилено'"""
		+ (" for update" if lock else ""),
		{"source": source.name},
		as_dict=True,
	)
	reserved = defaultdict(float)
	posted_items = {row.purchase_order_item for row in rows if row.purchase_order_item}
	posted = defaultdict(float)
	if posted_items:
		posted_rows = (
			frappe.db.sql(
				"""select material_request_item, stock_qty from `tabPurchase Order Item`
				where name in %(names)s and docstatus = 1 for update""",
				{"names": sorted(posted_items)},
				as_dict=True,
			)
			if lock
			else frappe.get_all(
				"Purchase Order Item",
				filters={"name": ["in", sorted(posted_items)], "docstatus": 1},
				fields=["material_request_item", "stock_qty"],
			)
		)
		for item in posted_rows:
			posted[item.material_request_item] += flt(item.stock_qty)
	for row in rows:
		if row.parent == exclude:
			continue
		original = source_items.get(row.material_request_item)
		if original:
			reserved[original.name] += flt(row.qty) * _stock_factor(row.item_code, row.uom, original)
	result = {}
	for original in source.items:
		factor = flt(original.conversion_factor) or 1
		requested = flt(original.stock_qty) or flt(original.qty) * factor
		# Submitted purchase orders already covered by a consolidated reservation are
		# counted once. Independent historical purchase orders still consume demand.
		external = max(0, flt(original.ordered_qty) - posted[original.name])
		used = reserved[original.name] + external
		result[original.name] = frappe._dict(
			item_code=original.item_code,
			requested_qty=requested / factor,
			reserved_qty=used / factor,
			remaining_qty=max(0, requested - used) / factor,
		)
	return result


@frappe.whitelist()
def get_material_request_coverage(source_name: str):
	source = frappe.get_doc("Material Request", source_name)
	source.check_permission("read")
	items = get_material_request_remaining(source)
	from erpnext.buying.procurement_automation import get_active_consolidated_purchase_order

	return {
		"items": items,
		"has_remaining": any(row.remaining_qty > 0.000001 for row in items.values()),
		"has_existing": bool(get_active_consolidated_purchase_order(source_name)),
	}


def validate_consolidated_request_quantities(doc):
	if doc.docstatus == 2 or doc.workflow_state == "Відхилено":
		return
	by_request = defaultdict(list)
	for row in doc.items:
		if row.material_request:
			by_request[row.material_request].append(row)
	for name, rows in sorted(by_request.items()):
		source = frappe.get_doc("Material Request", name, for_update=True)
		source.check_permission("read")
		if source.docstatus != 1 or source.material_request_type != "Purchase":
			frappe.throw(_("Material Request {0} must be a submitted purchase request.").format(name))
		originals = {row.name: row for row in source.items}
		remaining = get_material_request_remaining(source, exclude=doc.name, lock=True)
		selected = defaultdict(float)
		for row in rows:
			original = originals.get(row.material_request_item)
			if not original or original.item_code != row.item_code:
				frappe.throw(
					_("Row {0}: Select the matching original Material Request item.").format(row.idx)
				)
			factor = flt(original.conversion_factor) or 1
			selected[original.name] += flt(row.qty) * _stock_factor(row.item_code, row.uom, original) / factor
		for key, qty in selected.items():
			if qty > remaining[key].remaining_qty + 0.000001:
				frappe.throw(
					_(
						"Material Request {0}, item {1}: only {2} remains available for this consolidated order."
					).format(name, originals[key].item_code, remaining[key].remaining_qty)
				)


def limit_mapped_request_items(mapped_order, source_name):
	source = frappe.get_doc("Material Request", source_name)
	remaining = get_material_request_remaining(source)
	originals = {row.name: row for row in source.items}
	items = []
	for row in mapped_order.items:
		original = originals.get(row.material_request_item)
		available = remaining.get(row.material_request_item)
		if not original or not available or available.remaining_qty <= 0.000001:
			continue
		factor = _stock_factor(row.item_code, row.uom, original)
		qty = min(flt(row.qty), available.remaining_qty * (flt(original.conversion_factor) or 1) / factor)
		if qty <= 0.000001:
			continue
		row.qty = qty
		row.stock_qty = qty * factor
		row.amount = flt(row.rate) * qty
		items.append(row)
	mapped_order.set("items", items)
	if not items:
		frappe.throw(
			_("All items in this Material Request are already covered by active consolidated orders.")
		)


@frappe.whitelist()
def repeat_consolidated_order(source_name: str):
	require_buyer_role()
	source = frappe.get_doc("Consolidated Purchase Order", source_name)
	source.check_permission("read")
	if not frappe.has_permission("Consolidated Purchase Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	target = frappe.new_doc("Consolidated Purchase Order")
	target.company = source.company
	target.transaction_date = nowdate()
	target.currency = source.currency
	target.workflow_state = "Чернетка"
	target.initiator_user = frappe.session.user
	for row in source.items:
		values = {field: row.get(field) for field in REPEAT_ITEM_FIELDS}
		# Older orders predate the separate supplier-company column. Preserve an
		# explicit selection; otherwise use the supplier itself, as on the form.
		values["related_supplier"] = row.related_supplier or row.supplier
		values["schedule_date"] = max(getdate(row.schedule_date or nowdate()), getdate(nowdate()))
		target.append("items", values)
	# Copy an explicit allowlist, never invoices, deliveries, source links or approvals.
	target.request_initiator_user = None
	target.insert()
	return target
