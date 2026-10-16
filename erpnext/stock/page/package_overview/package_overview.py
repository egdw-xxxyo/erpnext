"""One read-only picture of the packed boxes: what waits to ship, what left, by item, and what is off.

A box's state is spread over the Package, its items, the Serial Nos inside (where they are now) and
the document that shipped it. This page puts them side by side so a storekeeper sees which boxes
wait, which items they hold, and which boxes disagree with their serials.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from erpnext.manufacturing.packing import staging_warehouses
from erpnext.stock.package_shipping import LINK_FIELD

# Who sees the page: whoever may run this report, so access is managed in one place.
ACCESS_REPORT = "Stock Balance"
HISTORY_DAYS = 14
STALE_DRAFT_DAYS = 1
UNPACKED_DAYS = 30


@frappe.whitelist()
def get_overview():
	check_access()

	rows = _rows()
	packages = _packages(rows)
	shipped_docs = _shipping_docs(packages)
	staging = staging_warehouses()

	for pkg in packages.values():
		_place(pkg, staging)

	open_boxes = [p for p in packages.values() if p["status"] in ("Packed", "Draft")]
	return {
		"generated_at": frappe.utils.now(),
		"today": today(),
		"history_days": HISTORY_DAYS,
		"counts": _status_counts(),
		"waiting": sorted(
			(_compact(p) for p in open_boxes if p["status"] == "Packed"), key=lambda p: p["created"]
		),
		"drafts": sorted(
			(_compact(p) for p in open_boxes if p["status"] == "Draft"), key=lambda p: p["created"]
		),
		"items": _by_item(packages),
		"shipments": _shipments(packages, shipped_docs),
		"history": _history(packages, shipped_docs),
		"unpacked": _unpacked(),
		"loose_shipped": _loose_shipped(),
		"issues": _issues(packages, shipped_docs),
	}


def check_access():
	report = frappe.get_doc("Report", ACCESS_REPORT)
	if not report.is_permitted() or not frappe.has_permission(report.ref_doctype, "report"):
		frappe.throw(_("You need access to the {0} report").format(_(ACCESS_REPORT)), frappe.PermissionError)


def _rows():
	return frappe.db.sql(
		"""
		SELECT p.name, p.status, p.creation, p.owner, p.packing_template, p.box_template,
			p.sales_order, p.bpak, p.pallet, p.delivery_note, p.sales_invoice, p.stock_entry,
			pi.item_code, pi.item_name, pi.serial_no, pi.qty,
			sn.warehouse, sn.status AS serial_status
		FROM `tabPackage` p
		LEFT JOIN `tabPackage Item` pi ON pi.parent = p.name AND pi.parenttype = 'Package'
		LEFT JOIN `tabSerial No` sn ON sn.name = pi.serial_no
		WHERE p.docstatus < 2
		ORDER BY p.name, pi.idx
		""",
		as_dict=True,
	)


def _packages(rows):
	packages = {}
	for row in rows:
		pkg = packages.get(row.name)
		if not pkg:
			pkg = packages[row.name] = {
				"name": row.name,
				"status": row.status,
				"created": row.creation,
				"owner": row.owner,
				"packing_template": row.packing_template,
				"box_template": row.box_template,
				"sales_order": row.sales_order,
				"bpak": row.bpak,
				"pallet": row.pallet,
				"delivery_note": row.delivery_note,
				"sales_invoice": row.sales_invoice,
				"stock_entry": row.stock_entry,
				"lines": [],
			}
		if row.item_code:
			pkg["lines"].append(row)
	return packages


def _place(pkg, staging):
	"""Where the serials of a box are now: warehouses, how many left stock, how many still in staging."""
	warehouses = {}
	gone = staging_count = 0
	for line in pkg["lines"]:
		if not line.serial_no:
			continue
		if line.warehouse:
			warehouses[line.warehouse] = warehouses.get(line.warehouse, 0) + 1
			staging_count += line.warehouse in staging
		else:
			gone += 1
	pkg["warehouses"] = warehouses
	pkg["gone"] = gone
	pkg["in_staging"] = staging_count
	pkg["serial_count"] = sum(1 for line in pkg["lines"] if line.serial_no)


def _contents(pkg):
	items = {}
	for line in pkg["lines"]:
		entry = items.setdefault(
			line.item_code, {"item_code": line.item_code, "item_name": line.item_name, "qty": 0}
		)
		entry["qty"] += line.qty or 1
	return list(items.values())


def _compact(pkg):
	age = (now_datetime() - pkg["created"]).total_seconds() if pkg["created"] else None
	return {
		"name": pkg["name"],
		"status": pkg["status"],
		"created": pkg["created"],
		"age": int(age) if age is not None else None,
		"owner": pkg["owner"],
		"packing_template": pkg["packing_template"],
		"sales_order": pkg["sales_order"],
		"bpak": pkg["bpak"],
		"pallet": pkg["pallet"],
		"contents": _contents(pkg),
		"serial_count": pkg["serial_count"],
		"serials": [line.serial_no for line in pkg["lines"] if line.serial_no],
		"warehouses": pkg["warehouses"],
		"gone": pkg["gone"],
		"in_staging": pkg["in_staging"],
	}


def _status_counts():
	rows = frappe.get_all("Package", fields=["status", {"COUNT": "*"}], group_by="status", as_list=True)
	return {status or "Draft": count for status, count in rows}


def _by_item(packages):
	out = {}
	for pkg in packages.values():
		for entry in _contents(pkg):
			row = out.setdefault(
				entry["item_code"],
				{
					"item_code": entry["item_code"],
					"item_name": entry["item_name"],
					"Draft": {"boxes": 0, "qty": 0},
					"Packed": {"boxes": 0, "qty": 0},
					"Shipped": {"boxes": 0, "qty": 0},
					"templates": {},
					"oldest_packed": None,
				},
			)
			if pkg["status"] not in ("Draft", "Packed", "Shipped"):
				continue
			row[pkg["status"]]["boxes"] += 1
			row[pkg["status"]]["qty"] += entry["qty"]
			if pkg["packing_template"]:
				row["templates"][pkg["packing_template"]] = (
					row["templates"].get(pkg["packing_template"], 0) + 1
				)
			if pkg["status"] == "Packed" and (
				not row["oldest_packed"] or pkg["created"] < row["oldest_packed"]
			):
				row["oldest_packed"] = pkg["created"]
	return sorted(out.values(), key=lambda r: (-r["Packed"]["qty"], r["item_code"]))


def _shipping_docs(packages):
	"""`{(doctype, name): {docstatus, date, party}}` for every document that shipped a box."""
	wanted = {}
	for pkg in packages.values():
		for doctype, field in LINK_FIELD.items():
			if pkg[field]:
				wanted.setdefault(doctype, set()).add(pkg[field])
	fields = {
		"Delivery Note": ["name", "docstatus", "posting_date", "customer AS party", "is_return"],
		"Sales Invoice": ["name", "docstatus", "posting_date", "customer AS party", "is_return"],
		"Stock Entry": ["name", "docstatus", "posting_date", "purpose AS party"],
	}
	docs = {}
	for doctype, names in wanted.items():
		for row in frappe.get_all(doctype, filters={"name": ["in", list(names)]}, fields=fields[doctype]):
			docs[(doctype, row.name)] = row
	return docs


def _shipped_by(pkg):
	for doctype, field in LINK_FIELD.items():
		if pkg[field]:
			return doctype, pkg[field]
	return None, None


def _shipments(packages, docs):
	out = {}
	for pkg in packages.values():
		if pkg["status"] != "Shipped":
			continue
		doctype, name = _shipped_by(pkg)
		doc = docs.get((doctype, name)) or {}
		row = out.setdefault(
			(doctype, name),
			{
				"doctype": doctype,
				"name": name,
				"date": doc.get("posting_date"),
				"party": doc.get("party"),
				"docstatus": doc.get("docstatus"),
				"boxes": 0,
				"qty": 0,
				"items": {},
			},
		)
		row["boxes"] += 1
		for entry in _contents(pkg):
			row["qty"] += entry["qty"]
			row["items"][entry["item_code"]] = row["items"].get(entry["item_code"], 0) + entry["qty"]
	return sorted(out.values(), key=lambda r: (str(r["date"] or ""), r["name"] or ""), reverse=True)


def _history(packages, docs):
	"""Boxes packed and shipped per day over the last `HISTORY_DAYS` days."""
	start = getdate(add_days(today(), -HISTORY_DAYS + 1))
	days = {str(add_days(start, i)): {"packed": 0, "shipped": 0} for i in range(HISTORY_DAYS)}
	for pkg in packages.values():
		if pkg["status"] in ("Packed", "Shipped") and pkg["created"]:
			day = str(getdate(pkg["created"]))
			if day in days:
				days[day]["packed"] += 1
		if pkg["status"] == "Shipped":
			doc = docs.get(_shipped_by(pkg)) or {}
			day = str(doc.get("posting_date") or "")
			if day in days:
				days[day]["shipped"] += 1
	return [{"date": day, **counts} for day, counts in days.items()]


def _unpacked():
	return frappe.get_all(
		"Package",
		filters={"status": "Unpacked", "modified": [">=", add_days(today(), -UNPACKED_DAYS)]},
		fields=["name", "modified", "packing_template", "modified_by"],
		order_by="modified desc",
		limit=200,
	)


def _loose_shipped():
	"""Serial numbers delivered in the last `HISTORY_DAYS` days that were never in any box."""
	return frappe.db.sql(
		"""
		SELECT sbb.voucher_no, sbb.posting_datetime, sbe.serial_no, sbb.item_code
		FROM `tabSerial and Batch Bundle` sbb
		JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sbb.name
		WHERE sbb.voucher_type = 'Delivery Note' AND sbb.type_of_transaction = 'Outward'
		  AND sbb.docstatus = 1 AND sbb.is_cancelled = 0
		  AND sbb.posting_datetime >= %(since)s
		  AND IFNULL(sbe.serial_no, '') != ''
		  AND NOT EXISTS (
			SELECT 1 FROM `tabPackage Item` pi JOIN `tabPackage` p ON p.name = pi.parent
			WHERE pi.serial_no = sbe.serial_no AND p.docstatus = 1
		  )
		ORDER BY sbb.posting_datetime DESC
		LIMIT 500
		""",
		{"since": add_days(today(), -HISTORY_DAYS + 1)},
		as_dict=True,
	)


def _issues(packages, docs):
	issues = []

	def add(level, area, message, doctype=None, name=None):
		issues.append({"level": level, "area": area, "message": message, "doctype": doctype, "name": name})

	for pkg in packages.values():
		name = pkg["name"]
		if pkg["status"] == "Packed":
			if pkg["gone"] and pkg["gone"] == pkg["serial_count"]:
				add(
					"error",
					"Package",
					_("All {0} serials left stock but the box is still Packed").format(pkg["gone"]),
					"Package",
					name,
				)
			elif pkg["gone"]:
				add(
					"error",
					"Package",
					_("Partially shipped: {0} of {1} serials left stock").format(
						pkg["gone"], pkg["serial_count"]
					),
					"Package",
					name,
				)
			if len(pkg["warehouses"]) > 1:
				add(
					"warning",
					"Package",
					_("Serials of one box stand in different warehouses: {0}").format(
						", ".join(pkg["warehouses"])
					),
					"Package",
					name,
				)
			if pkg["in_staging"]:
				add(
					"warning",
					"Package",
					_("{0} serials are packed but still stand in a staging warehouse").format(
						pkg["in_staging"]
					),
					"Package",
					name,
				)
			if not pkg["serial_count"]:
				add("info", "Package", _("Packed box without serial numbers"), "Package", name)
		elif pkg["status"] == "Shipped":
			doctype, doc_name = _shipped_by(pkg)
			doc = docs.get((doctype, doc_name))
			if not doc_name:
				add("warning", "Package", _("Shipped box without a shipping document"), "Package", name)
			elif not doc or doc.docstatus != 1:
				add(
					"error",
					"Package",
					_("Shipped by {0} {1}, which is not submitted").format(_(doctype), doc_name),
					"Package",
					name,
				)
			if pkg["warehouses"]:
				add(
					"warning",
					"Package",
					_("Shipped box but {0} serials are back in stock: {1}").format(
						sum(pkg["warehouses"].values()), ", ".join(pkg["warehouses"])
					),
					"Package",
					name,
				)
		elif pkg["status"] == "Draft" and pkg["created"]:
			days = (now_datetime() - pkg["created"]).days
			if days >= STALE_DRAFT_DAYS:
				add(
					"warning",
					"Package",
					_("Draft box not finished for {0} days").format(days),
					"Package",
					name,
				)

	for serial, boxes in _serials_in_many_boxes().items():
		add(
			"error",
			"Serial No",
			_("Serial number is in several open boxes: {0}").format(", ".join(boxes)),
			"Serial No",
			serial,
		)

	order = {"error": 0, "warning": 1, "info": 2}
	return sorted(issues, key=lambda i: (order[i["level"]], i["name"] or ""))


def _serials_in_many_boxes():
	rows = frappe.db.sql(
		"""
		SELECT pi.serial_no, GROUP_CONCAT(p.name ORDER BY p.name) AS boxes
		FROM `tabPackage Item` pi JOIN `tabPackage` p ON p.name = pi.parent
		WHERE p.docstatus = 1 AND p.status = 'Packed' AND IFNULL(pi.serial_no, '') != ''
		GROUP BY pi.serial_no HAVING COUNT(*) > 1
		""",
		as_dict=True,
	)
	return {row.serial_no: row.boxes.split(",") for row in rows}
