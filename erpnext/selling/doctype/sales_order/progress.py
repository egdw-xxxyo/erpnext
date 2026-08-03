import frappe


@frappe.whitelist()
def get_attachment_progress(sales_order):
	"""Return per-item planned vs attached counts and Package status breakdown."""
	if not sales_order or not frappe.db.exists("Sales Order", sales_order):
		return {}

	so = frappe.get_doc("Sales Order", sales_order)

	planned = {}
	for it in so.get("items") or []:
		if not it.item_code:
			continue
		qty = float(it.qty or 0)
		if (it.get("source_type") or "Direct") == "Direct":
			planned[it.item_code] = planned.get(it.item_code, 0) + qty

	attached = _attached_qty_by_item(so)

	rows = []
	for code in sorted(set(list(planned) + list(attached))):
		p = planned.get(code, 0)
		a = attached.get(code, 0)
		pct = round(min(a, p) / p * 100, 1) if p else (100.0 if a else 0.0)
		rows.append(
			{
				"item_code": code,
				"planned": p,
				"attached": a,
				"remaining": max(p - a, 0),
				"over": max(a - p, 0) if p else 0,
				"pct": pct,
			}
		)

	total_planned = sum(planned.values())
	total_attached = sum(attached.values())
	overall_pct = (
		round(min(total_attached, total_planned) / total_planned * 100, 1)
		if total_planned
		else (100.0 if total_attached else 0.0)
	)

	package_names = set()
	for sopkg in so.get("packages") or []:
		if sopkg.package:
			package_names.add(sopkg.package)
	for sop in so.get("pallets") or []:
		if sop.pallet:
			for n in frappe.get_all(
				"Package",
				filters={"pallet": sop.pallet, "docstatus": ["<", 2]},
				pluck="name",
			):
				package_names.add(n)
	for sob in so.get("bpaks") or []:
		if sob.bpak:
			for n in frappe.get_all(
				"Package",
				filters={"bpak": sob.bpak, "docstatus": ["<", 2]},
				pluck="name",
			):
				package_names.add(n)

	pkg_status = {"Draft": 0, "Packed": 0, "Shipped": 0, "Cancelled": 0}
	for n in package_names:
		s = frappe.db.get_value("Package", n, "status") or "Draft"
		pkg_status[s] = pkg_status.get(s, 0) + 1

	pallet_status = {"Draft": 0, "Packed": 0, "Shipped": 0, "Cancelled": 0}
	for sop in so.get("pallets") or []:
		if sop.pallet:
			s = frappe.db.get_value("Pallet", sop.pallet, "status") or "Draft"
			pallet_status[s] = pallet_status.get(s, 0) + 1

	tree = _build_attachment_tree(so)

	return {
		"rows": rows,
		"total_planned": total_planned,
		"total_attached": total_attached,
		"overall_pct": overall_pct,
		"package_count": len(package_names),
		"package_status": pkg_status,
		"pallet_count": len(so.get("pallets") or []),
		"pallet_status": pallet_status,
		"bpak_count": len(so.get("bpaks") or []),
		"tree": tree,
	}


def _build_attachment_tree(so):
	def pkg_items(name):
		return frappe.get_all(
			"Package Item",
			filters={"parent": name, "parenttype": "Package"},
			fields=["item_code", "qty", "serial_no"],
			order_by="idx asc",
		)

	def pkg_meta(name):
		return frappe.db.get_value("Package", name, ["status", "bpak", "pallet"], as_dict=True) or {}

	seen = set()
	pallets = []
	for sop in so.get("pallets") or []:
		if not sop.pallet:
			continue
		pkgs = frappe.get_all(
			"Package",
			filters={"pallet": sop.pallet, "docstatus": ["<", 2]},
			fields=["name", "status", "bpak"],
		)
		pkg_nodes = []
		for p in pkgs:
			seen.add(p.name)
			pkg_nodes.append(
				{
					"name": p.name,
					"status": p.status,
					"bpak": p.bpak,
					"items": pkg_items(p.name),
				}
			)
		pallets.append(
			{
				"name": sop.pallet,
				"status": frappe.db.get_value("Pallet", sop.pallet, "status"),
				"packages": pkg_nodes,
			}
		)

	bpaks = []
	for sob in so.get("bpaks") or []:
		if not sob.bpak:
			continue
		pkgs = frappe.get_all(
			"Package",
			filters={"bpak": sob.bpak, "docstatus": ["<", 2]},
			fields=["name", "status", "pallet"],
		)
		pkg_nodes = []
		for p in pkgs:
			if p.name in seen:
				continue
			seen.add(p.name)
			pkg_nodes.append(
				{
					"name": p.name,
					"status": p.status,
					"pallet": p.pallet,
					"items": pkg_items(p.name),
				}
			)
		planned = []
		if not pkg_nodes:
			planned = frappe.get_all(
				"BpAK Planned Item",
				filters={"parent": sob.bpak, "parenttype": "BpAK"},
				fields=["item_code", "qty"],
				order_by="idx asc",
			)
		bpaks.append(
			{
				"name": sob.bpak,
				"status": frappe.db.get_value("BpAK", sob.bpak, "status"),
				"packages": pkg_nodes,
				"planned": planned,
			}
		)

	packages = []
	for sopkg in so.get("packages") or []:
		if not sopkg.package or sopkg.package in seen:
			continue
		seen.add(sopkg.package)
		meta = pkg_meta(sopkg.package)
		packages.append(
			{
				"name": sopkg.package,
				"status": meta.get("status"),
				"bpak": meta.get("bpak"),
				"pallet": meta.get("pallet"),
				"items": pkg_items(sopkg.package),
			}
		)

	return {"pallets": pallets, "bpaks": bpaks, "packages": packages}


def _attached_qty_by_item(so):
	seen_packages = set()
	for sopkg in so.get("packages") or []:
		if sopkg.package:
			seen_packages.add(sopkg.package)
	for sop in so.get("pallets") or []:
		if sop.pallet:
			for n in frappe.get_all(
				"Package",
				filters={"pallet": sop.pallet, "docstatus": ["<", 2]},
				pluck="name",
			):
				seen_packages.add(n)
	for sob in so.get("bpaks") or []:
		if sob.bpak:
			for n in frappe.get_all(
				"Package",
				filters={"bpak": sob.bpak, "docstatus": ["<", 2]},
				pluck="name",
			):
				seen_packages.add(n)
	if not seen_packages:
		return {}
	rows = frappe.get_all(
		"Package Item",
		filters={"parent": ["in", list(seen_packages)], "parenttype": "Package"},
		fields=["item_code", "qty"],
	)
	out = {}
	for r in rows:
		if not r.item_code:
			continue
		out[r.item_code] = out.get(r.item_code, 0) + float(r.qty or 0)
	return out


def update_so_progress(sales_order):
	"""Recompute attachment status indicators on SO child rows. Safe to call
	from Package/Pallet/BpAK hooks. Does NOT touch per_delivered / per_billed."""
	if not sales_order:
		return
	if not frappe.db.exists("Sales Order", sales_order):
		return

	so = frappe.get_doc("Sales Order", sales_order)
	dirty = False

	for sopkg in so.get("packages") or []:
		if not sopkg.package:
			continue
		status = frappe.db.get_value("Package", sopkg.package, "status")
		if status and sopkg.status != status:
			sopkg.db_set("status", status, update_modified=False)
			dirty = True

	for sop in so.get("pallets") or []:
		if not sop.pallet:
			continue
		status = frappe.db.get_value("Pallet", sop.pallet, "status")
		pkg_count = frappe.db.count("Package", {"pallet": sop.pallet, "docstatus": ["<", 2]})
		if status and sop.status != status:
			sop.db_set("status", status, update_modified=False)
			dirty = True
		if sop.package_count != pkg_count:
			sop.db_set("package_count", pkg_count, update_modified=False)
			dirty = True

	for sob in so.get("bpaks") or []:
		if not sob.bpak:
			continue
		status = frappe.db.get_value("BpAK", sob.bpak, "status")
		if status and sob.status != status:
			sob.db_set("status", status, update_modified=False)
			dirty = True

	return dirty
