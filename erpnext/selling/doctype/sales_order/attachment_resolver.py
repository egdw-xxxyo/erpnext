import frappe
from frappe.utils import flt


def flatten_attachment(so):
	"""Walk Pallets -> Packages, BpAKs -> Packages (or planned_items), direct Packages.
	Return list of dicts ready to insert into Sales Order Item.
	Dedupes by Package name (Pallet > BpAK > direct order)."""
	seen_packages = set()
	rows = []

	for sop in so.get("pallets") or []:
		if not sop.pallet:
			continue
		pkgs = frappe.get_all(
			"Package",
			filters={"pallet": sop.pallet, "docstatus": ["<", 2], "status": ["!=", "Cancelled"]},
			fields=["name", "bpak"],
		)
		for pkg in pkgs:
			if pkg.name in seen_packages:
				continue
			seen_packages.add(pkg.name)
			_append_package_items(rows, pkg.name, pallet=sop.pallet, bpak=pkg.bpak)

	for sob in so.get("bpaks") or []:
		if not sob.bpak:
			continue
		pkgs = frappe.get_all(
			"Package",
			filters={"bpak": sob.bpak, "docstatus": ["<", 2], "status": ["!=", "Cancelled"]},
			fields=["name", "pallet"],
		)
		used_real = False
		for pkg in pkgs:
			if pkg.name in seen_packages:
				used_real = True
				continue
			seen_packages.add(pkg.name)
			_append_package_items(rows, pkg.name, pallet=pkg.pallet, bpak=sob.bpak)
			used_real = True
		if not used_real:
			_append_bpak_planned(rows, sob.bpak)

	for sopkg in so.get("packages") or []:
		if not sopkg.package or sopkg.package in seen_packages:
			continue
		seen_packages.add(sopkg.package)
		pkg = frappe.db.get_value(
			"Package", sopkg.package, ["pallet", "bpak"], as_dict=True
		)
		_append_package_items(
			rows, sopkg.package,
			pallet=pkg.pallet if pkg else None,
			bpak=pkg.bpak if pkg else None,
		)

	return rows


def _append_package_items(rows, package_name, pallet=None, bpak=None):
	pkg_items = frappe.get_all(
		"Package Item",
		filters={"parent": package_name, "parenttype": "Package"},
		fields=["item_code", "item_name", "qty", "serial_no"],
		order_by="idx asc",
	)
	for idx, pi in enumerate(pkg_items):
		if not pi.item_code:
			continue
		rows.append({
			"item_code": pi.item_code,
			"item_name": pi.item_name,
			"qty": flt(pi.qty) or 1,
			"source_type": "Package",
			"source_package": package_name,
			"source_bpak": bpak,
			"source_pallet": pallet,
			"source_row_key": f"pkg:{package_name}|item:{pi.item_code}|idx:{idx}",
		})


def _append_bpak_planned(rows, bpak_name):
	planned = frappe.get_all(
		"BpAK Planned Item",
		filters={"parent": bpak_name, "parenttype": "BpAK"},
		fields=["item_code", "item_name", "qty", "uom"],
		order_by="idx asc",
	)
	for idx, p in enumerate(planned):
		if not p.item_code:
			continue
		rows.append({
			"item_code": p.item_code,
			"item_name": p.item_name,
			"qty": flt(p.qty) or 1,
			"uom": p.uom,
			"source_type": "BpAK",
			"source_package": None,
			"source_bpak": bpak_name,
			"source_pallet": None,
			"source_row_key": f"bpak:{bpak_name}|item:{p.item_code}|idx:{idx}",
		})


def collect_serials(so):
	"""Return {item_code: [serial_no, ...]} from all Packages reachable via
	pallets, bpaks, direct, and via Package.sales_order back-link."""
	seen_packages = set()

	for sop in so.get("pallets") or []:
		if sop.pallet:
			for pkg in frappe.get_all(
				"Package",
				filters={"pallet": sop.pallet, "docstatus": 1, "status": ["!=", "Cancelled"]},
				pluck="name",
			):
				seen_packages.add(pkg)

	for sob in so.get("bpaks") or []:
		if sob.bpak:
			for pkg in frappe.get_all(
				"Package",
				filters={"bpak": sob.bpak, "docstatus": 1, "status": ["!=", "Cancelled"]},
				pluck="name",
			):
				seen_packages.add(pkg)

	for sopkg in so.get("packages") or []:
		if sopkg.package:
			seen_packages.add(sopkg.package)

	for pkg in frappe.get_all(
		"Package",
		filters={"sales_order": so.name, "docstatus": 1, "status": ["!=", "Cancelled"]},
		pluck="name",
	):
		seen_packages.add(pkg)

	if not seen_packages:
		return {}

	rows = frappe.get_all(
		"Package Item",
		filters={
			"parent": ["in", list(seen_packages)],
			"parenttype": "Package",
			"serial_no": ["is", "set"],
		},
		fields=["item_code", "serial_no"],
	)
	serials_by_item = {}
	for r in rows:
		if not r.serial_no:
			continue
		serials_by_item.setdefault(r.item_code, []).append(r.serial_no)
	return serials_by_item


def sync_items_from_attachments(so):
	"""Remove items with source_type != Direct, re-insert flattened rows.
	Preserve Direct rows untouched."""
	has_attachments = bool(
		(so.get("pallets") or []) or (so.get("packages") or []) or (so.get("bpaks") or [])
	)

	kept = []
	for it in so.get("items") or []:
		source = it.get("source_type") or "Direct"
		if source != "Direct":
			continue
		if it.get("bpak_row"):
			continue
		kept.append(it)

	if not has_attachments:
		so.set("items", kept)
		return

	from erpnext.stock.get_item_details import get_price_list_rate
	from erpnext.stock.doctype.item.item import get_item_defaults

	flattened = flatten_attachment(so)

	direct_item_codes = {it.item_code for it in kept if it.item_code}

	so.set("items", kept)
	for r in flattened:
		if r["item_code"] in direct_item_codes:
			continue
		new_row = so.append("items", {
			"item_code": r["item_code"],
			"item_name": r.get("item_name"),
			"qty": r["qty"],
			"uom": r.get("uom"),
			"delivery_date": so.delivery_date,
			"warehouse": so.set_warehouse,
			"source_type": r["source_type"],
			"source_package": r.get("source_package"),
			"source_bpak": r.get("source_bpak"),
			"source_pallet": r.get("source_pallet"),
			"source_row_key": r["source_row_key"],
		})
		_apply_default_rate(so, new_row, get_price_list_rate, get_item_defaults)


def _apply_default_rate(so, row, get_price_list_rate, get_item_defaults):
	if not row.item_code:
		return
	try:
		defaults = get_item_defaults(row.item_code, so.company) or {}
		if not row.uom:
			row.uom = defaults.get("stock_uom") or frappe.db.get_value(
				"Item", row.item_code, "stock_uom"
			)
		row.stock_uom = row.uom
		row.conversion_factor = 1
		if so.selling_price_list:
			args = frappe._dict({
				"item_code": row.item_code,
				"price_list": so.selling_price_list,
				"qty": row.qty,
				"uom": row.uom,
				"transaction_date": so.transaction_date,
				"customer": so.customer,
				"currency": so.currency,
				"plc_conversion_rate": so.plc_conversion_rate or 1,
				"conversion_rate": so.conversion_rate or 1,
				"company": so.company,
				"doctype": "Sales Order",
			})
			price = get_price_list_rate(args, frappe.get_cached_doc("Item", row.item_code)) or {}
			if price.get("price_list_rate"):
				row.rate = price["price_list_rate"]
				row.price_list_rate = price["price_list_rate"]
		if not row.rate:
			std = frappe.db.get_value("Item", row.item_code, "standard_rate")
			if std:
				row.rate = std
				row.price_list_rate = std
	except Exception:
		frappe.log_error(
			title="SO attachment rate fetch",
			message=frappe.get_traceback(),
		)
