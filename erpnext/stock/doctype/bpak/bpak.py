# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class BpAK(Document):
	def validate(self):
		self._inherit_from_template()
		self._resolve_serial_series()
		self._reconcile_packages_link()

	def before_submit(self):
		if not self.serial_no:
			self.serial_no = self._issue_serial_no()
		self.status = "Packing"

	def on_update(self):
		if not self.is_new():
			sync_packages_child(self.name)

	def on_cancel(self):
		self.status = "Cancelled"

	def _reconcile_packages_link(self):
		"""Sync `Package.bpak` to match this BpAK's `packages` child table.
		- Added rows: claim the Package (reject if linked to another BpAK).
		- Removed rows: clear `Package.bpak` if it currently points here."""
		if self.is_new():
			return
		desired = []
		seen = set()
		for row in self.packages or []:
			if not row.package:
				continue
			if row.package in seen:
				frappe.throw(_("Duplicate package row: {0}").format(row.package))
			seen.add(row.package)
			desired.append(row.package)

		current = {
			p.name for p in frappe.get_all("Package", filters={"bpak": self.name}, fields=["name"])
		}
		to_add = set(desired) - current
		to_remove = current - set(desired)

		for pkg_name in to_add:
			info = frappe.db.get_value(
				"Package", pkg_name, ["name", "bpak", "docstatus"], as_dict=True
			)
			if not info:
				frappe.throw(_("Package {0} not found").format(pkg_name))
			if info.bpak and info.bpak != self.name:
				frappe.throw(
					_("Package {0} is already linked to BpAK {1}").format(pkg_name, info.bpak)
				)
			frappe.db.set_value("Package", pkg_name, "bpak", self.name, update_modified=False)

		for pkg_name in to_remove:
			frappe.db.set_value("Package", pkg_name, "bpak", None, update_modified=False)

	def _inherit_from_template(self):
		if not self.bpak_template:
			return
		template = frappe.get_cached_doc("BpAK Template", self.bpak_template)
		self.serial_number_template = template.serial_number_template

	def _resolve_serial_series(self):
		if not self.serial_number_template or not self.bpak_template:
			self.serial_no_series = None
			return
		template = frappe.get_cached_doc("BpAK Template", self.bpak_template)
		snt = frappe.get_doc("Serial Number Template", self.serial_number_template)
		attr_map = {row.attribute: row.attribute_value for row in (template.attributes or [])}
		self.serial_no_series = snt.resolve_series_from_attributes(
			attr_map, context_label=f"BpAK '{self.name or self.bpak_template}'"
		)

	def _issue_serial_no(self):
		if not self.serial_no_series:
			frappe.throw("Cannot issue serial number: serial_no_series is empty.")
		return make_autoname(self.serial_no_series)


@frappe.whitelist()
def get_attribute_values(attribute):
	if not attribute:
		return []
	rows = frappe.db.get_all(
		"Item Attribute Value",
		filters={"parent": attribute, "parenttype": "Item Attribute"},
		fields=["attribute_value"],
		order_by="idx asc",
		limit_page_length=0,
	)
	return [r.attribute_value for r in rows if r.attribute_value]


def create_bpaks_on_so_submit(doc, method=None):
	"""before_submit hook on Sales Order. Link each attached BpAK back to the SO
	(set sales_order, customer) so the BpAK knows which order it serves."""
	if not doc.get("delivered_in_bpaks"):
		return
	if not doc.get("bpaks"):
		return
	for row in doc.bpaks:
		if not row.bpak:
			frappe.throw(f"BpAK row #{row.idx}: BpAK link is required.")
		bpak = frappe.get_doc("BpAK", row.bpak)
		if not bpak.sales_order:
			bpak.db_set("sales_order", doc.name, update_modified=False)
		if not bpak.customer:
			bpak.db_set("customer", doc.customer, update_modified=False)
		row.serial_no = bpak.serial_no
		row.status = bpak.status


@frappe.whitelist()
def create_and_attach(bpak_template, items, sales_order=None, customer=None):
	"""Create a new BpAK with planned items and return its name so the caller
	can attach it to a Sales Order's `bpaks` grid."""
	items = frappe.parse_json(items) if isinstance(items, str) else (items or [])
	if not bpak_template:
		frappe.throw("BpAK Template is required.")
	if not items:
		frappe.throw("At least one planned item is required.")
	bpak = frappe.new_doc("BpAK")
	bpak.bpak_template = bpak_template
	if customer:
		bpak.customer = customer
	if sales_order:
		bpak.sales_order = sales_order
	for it in items:
		if not it.get("item_code"):
			continue
		bpak.append("planned_items", {
			"item_code": it.get("item_code"),
			"qty": it.get("qty") or 1,
			"uom": it.get("uom"),
		})
	bpak.insert(ignore_permissions=True)
	bpak.submit()
	return {
		"name": bpak.name,
		"serial_no": bpak.serial_no,
		"status": bpak.status,
		"planned_items": [
			{"item_code": p.item_code, "qty": p.qty, "uom": p.uom}
			for p in bpak.planned_items
		],
	}


@frappe.whitelist()
def refresh_bpak_aggregates(sales_order):
	"""Recompute package_count / item_count for each linked BpAK on the SO,
	and refresh the qty on SO Items rows from packages' actual contents."""
	so = frappe.get_doc("Sales Order", sales_order)
	if not so.get("bpaks"):
		return {"updated": 0}

	# Aggregate per item_code from Package Item rows under each linked BpAK
	totals_by_item = {}
	for row in so.bpaks:
		if not row.bpak:
			continue
		pkgs = frappe.get_all(
			"Package",
			filters={"bpak": row.bpak, "docstatus": ["<", 2]},
			fields=["name", "status"],
		)
		row.package_count = len(pkgs)
		item_total = 0
		pkg_item_counts = {}
		if pkgs:
			pkg_names = [p.name for p in pkgs]
			rows = frappe.get_all(
				"Package Item",
				filters={"parent": ["in", pkg_names], "parenttype": "Package"},
				fields=["parent", "item_code", "qty"],
			)
			for r in rows:
				q = int(r.qty or 0)
				item_total += q
				pkg_item_counts[r.parent] = pkg_item_counts.get(r.parent, 0) + q
				totals_by_item[r.item_code] = totals_by_item.get(r.item_code, 0) + q
		row.item_count = item_total

		# Sync BpAK.packages child table
		bpak = frappe.get_doc("BpAK", row.bpak)
		bpak.set("packages", [])
		for p in pkgs:
			bpak.append("packages", {
				"package": p.name,
				"status": p.status,
				"item_count": pkg_item_counts.get(p.name, 0),
			})
		bpak.flags.ignore_validate_update_after_submit = True
		bpak.save(ignore_permissions=True)

	# Update SO Items qty from aggregated totals (only items already on the SO)
	for it in so.items or []:
		if it.item_code in totals_by_item:
			it.qty = totals_by_item[it.item_code]

	so.flags.ignore_validate_update_after_submit = True
	so.save(ignore_permissions=True)
	return {"updated": len(so.bpaks)}


@frappe.whitelist()
def get_packed_summary(bpak_name):
	"""Return per-package item breakdown plus packed/planned totals for a BpAK."""
	if not bpak_name:
		return {"packages": [], "packed_total": 0, "planned_total": 0}

	planned = frappe.get_all(
		"BpAK Planned Item",
		filters={"parent": bpak_name, "parenttype": "BpAK"},
		fields=["item_code", "qty"],
	)
	planned_total = sum(int(p.qty or 0) for p in planned)

	pkgs = frappe.get_all(
		"Package",
		filters={"bpak": bpak_name, "docstatus": ["<", 2]},
		fields=["name", "status"],
		order_by="creation asc",
	)
	packages = []
	packed_total = 0
	if pkgs:
		rows = frappe.get_all(
			"Package Item",
			filters={"parent": ["in", [p.name for p in pkgs]], "parenttype": "Package"},
			fields=["parent", "item_code", "item_name", "qty", "serial_no"],
			order_by="parent asc, idx asc",
		)
		grouped = {}
		for r in rows:
			grouped.setdefault(r.parent, []).append({
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": int(r.qty or 0),
				"serial_no": r.serial_no,
			})
			packed_total += int(r.qty or 0)
		for p in pkgs:
			packages.append({
				"name": p.name,
				"status": p.status,
				"items": grouped.get(p.name, []),
			})

	return {
		"packages": packages,
		"packed_total": packed_total,
		"planned_total": planned_total,
	}


def update_status_from_package(bpak_name):
	"""Recompute BpAK status based on linked Packages. Called from Package hooks."""
	if not bpak_name:
		return
	bpak = frappe.get_doc("BpAK", bpak_name)
	if bpak.docstatus != 1:
		return

	packages = frappe.get_all(
		"Package",
		filters={"bpak": bpak_name, "docstatus": ["<", 2]},
		fields=["status"],
	)
	if not packages:
		new_status = "Packing"
	elif all(p.status == "Shipped" for p in packages):
		new_status = "Shipped"
	elif all(p.status in ("Packed", "Shipped") for p in packages):
		new_status = "Packed"
	else:
		new_status = "Packing"

	if bpak.status != new_status:
		frappe.db.set_value("BpAK", bpak_name, "status", new_status)

	sync_packages_child(bpak_name)


def sync_packages_child(bpak_name):
	"""Rebuild BpAK.packages child table from current linked Packages."""
	if not bpak_name or not frappe.db.exists("BpAK", bpak_name):
		return
	pkgs = frappe.get_all(
		"Package",
		filters={"bpak": bpak_name, "docstatus": ["<", 2]},
		fields=["name", "status"],
		order_by="creation asc",
	)
	item_counts = {}
	if pkgs:
		rows = frappe.get_all(
			"Package Item",
			filters={"parent": ["in", [p.name for p in pkgs]], "parenttype": "Package"},
			fields=["parent", "qty"],
		)
		for r in rows:
			item_counts[r.parent] = item_counts.get(r.parent, 0) + int(r.qty or 0)

	frappe.db.delete("BpAK Package", {"parent": bpak_name, "parenttype": "BpAK"})
	for idx, p in enumerate(pkgs, start=1):
		row = frappe.get_doc({
			"doctype": "BpAK Package",
			"parent": bpak_name,
			"parenttype": "BpAK",
			"parentfield": "packages",
			"idx": idx,
			"package": p.name,
			"status": p.status,
			"item_count": item_counts.get(p.name, 0),
		})
		row.db_insert()
