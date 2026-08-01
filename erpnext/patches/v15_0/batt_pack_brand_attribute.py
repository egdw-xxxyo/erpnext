"""Add brand (Торгова марка) dimension to BATT-PACK variants.

- adds Магура/M to the brand attribute
- puts the brand attribute first on the BATT-PACK template
- replaces the hardcoded "UB0" literal in the serial template with {ATTR:Торгова марка} + "B0"
- backfills existing variants with Укропчик and renames them to BATT-PACK-U-*

Child rows are written with SQL on purpose: Item.validate_stock_exists_for_template_item
blocks attribute changes on items that already have stock ledger entries.
"""

import frappe
from frappe.utils import now

BRAND = "Торгова марка"
TEMPLATE = "BATT-PACK"
TEMPLATE_NAME = "Батарейний блок"
SNT = "СН батарейного блоку"
DEFAULT_BRAND = "Укропчик"
DEFAULT_ABBR = "U"
BRAND_VALUES = [("Укропчик", "U"), ("Магура", "M")]


def execute():
	if not frappe.db.exists("Item", TEMPLATE):
		return

	ensure_brand_values()
	ensure_template_attribute()
	rewrite_serial_template()
	backfill_variants()
	frappe.db.commit()
	frappe.clear_cache()


def ensure_brand_values():
	if not frappe.db.exists("Item Attribute", BRAND):
		frappe.get_doc({"doctype": "Item Attribute", "attribute_name": BRAND}).insert()

	for value, abbr in BRAND_VALUES:
		if frappe.db.exists("Item Attribute Value", {"parent": BRAND, "attribute_value": value}):
			continue
		insert_child(
			"Item Attribute Value",
			parent=BRAND,
			parenttype="Item Attribute",
			parentfield="item_attribute_values",
			values={"attribute_value": value, "abbr": abbr},
		)


def ensure_template_attribute():
	"""Brand must be the first attribute so variant codes read BATT-PACK-U-LI-..."""
	row = frappe.db.get_value(
		"Item Variant Attribute", {"parent": TEMPLATE, "attribute": BRAND}, ["name", "idx"], as_dict=True
	)
	if row and row.idx == 1:
		return

	if row:
		frappe.db.sql(
			"update `tabItem Variant Attribute` set idx = idx + 1 where parent = %s and idx < %s",
			(TEMPLATE, row.idx),
		)
		frappe.db.set_value("Item Variant Attribute", row.name, "idx", 1, update_modified=False)
		return

	frappe.db.sql("update `tabItem Variant Attribute` set idx = idx + 1 where parent = %s", TEMPLATE)
	insert_child(
		"Item Variant Attribute",
		parent=TEMPLATE,
		parenttype="Item",
		parentfield="attributes",
		values={"attribute": BRAND},
		idx=1,
	)


def rewrite_serial_template():
	if not frappe.db.exists("Serial Number Template", SNT):
		return

	first = frappe.db.get_value(
		"Serial Number Template Component",
		{"parent": SNT, "idx": 1},
		["name", "component_type", "value"],
		as_dict=True,
	)
	if not first or first.component_type != "Literal" or first.value != "UB0":
		return

	frappe.db.sql(
		"update `tabSerial Number Template Component` set idx = idx + 1 where parent = %s and idx > 1",
		SNT,
	)
	frappe.db.set_value(
		"Serial Number Template Component",
		first.name,
		{"component_type": "Item Attribute", "attribute_link": BRAND, "value": None},
		update_modified=False,
	)
	insert_child(
		"Serial Number Template Component",
		parent=SNT,
		parenttype="Serial Number Template",
		parentfield="components",
		values={"component_type": "Literal", "value": "B0"},
		idx=2,
	)

	series = template_series()
	frappe.db.set_value("Serial Number Template", SNT, "resulting_series", series, update_modified=False)
	frappe.db.set_value("Item", TEMPLATE, "serial_no_series", series, update_modified=False)


def template_series():
	return frappe.db.get_value("Serial Number Template", SNT, "resulting_series").replace(
		"UB0", "{ATTR:" + BRAND + "}.B0", 1
	)


def backfill_variants():
	series = frappe.db.get_value("Item", TEMPLATE, "serial_no_series") or ""

	for item_code in frappe.get_all("Item", filters={"variant_of": TEMPLATE}, pluck="name"):
		add_brand_row(item_code)
		resolve_series(item_code, series)
		rename_with_brand(item_code)


def add_brand_row(item_code):
	row = frappe.db.get_value(
		"Item Variant Attribute", {"parent": item_code, "attribute": BRAND}, ["name", "idx"], as_dict=True
	)
	if row:
		if row.idx != 1:
			frappe.db.sql(
				"update `tabItem Variant Attribute` set idx = idx + 1 where parent = %s and idx < %s",
				(item_code, row.idx),
			)
			frappe.db.set_value("Item Variant Attribute", row.name, "idx", 1, update_modified=False)
		return

	frappe.db.sql("update `tabItem Variant Attribute` set idx = idx + 1 where parent = %s", item_code)
	insert_child(
		"Item Variant Attribute",
		parent=item_code,
		parenttype="Item",
		parentfield="attributes",
		values={"attribute": BRAND, "attribute_value": DEFAULT_BRAND},
		idx=1,
	)


def resolve_series(item_code, series):
	if "{ATTR:" not in series:
		return

	resolved = series
	rows = frappe.db.sql(
		"select attribute, attribute_value from `tabItem Variant Attribute` where parent = %s", item_code
	)
	for attribute, value in rows:
		abbr = frappe.db.get_value(
			"Item Attribute Value", {"parent": attribute, "attribute_value": value}, "abbr"
		)
		if abbr:
			resolved = resolved.replace("{ATTR:" + attribute + "}", abbr)

	frappe.db.set_value("Item", item_code, "serial_no_series", resolved, update_modified=False)


def rename_with_brand(item_code):
	prefix = TEMPLATE + "-"
	branded_prefix = prefix + DEFAULT_ABBR + "-"
	if not item_code.startswith(prefix) or item_code.startswith(branded_prefix):
		return

	new_code = branded_prefix + item_code[len(prefix) :]
	if frappe.db.exists("Item", new_code):
		return

	frappe.rename_doc("Item", item_code, new_code, force=True, show_alert=False)

	item_name = frappe.db.get_value("Item", new_code, "item_name") or ""
	name_prefix = TEMPLATE_NAME + "-"
	if item_name.startswith(name_prefix) and not item_name.startswith(name_prefix + DEFAULT_ABBR + "-"):
		frappe.db.set_value(
			"Item",
			new_code,
			"item_name",
			name_prefix + DEFAULT_ABBR + "-" + item_name[len(name_prefix) :],
			update_modified=False,
		)


def insert_child(doctype, parent, parenttype, parentfield, values, idx=None):
	if idx is None:
		idx = (
			frappe.db.sql(
				"select ifnull(max(idx), 0) + 1 from `tab{0}` where parent = %s".format(doctype), parent
			)[0][0]
			or 1
		)

	row = {
		"name": frappe.generate_hash(length=10),
		"creation": now(),
		"modified": now(),
		"owner": "Administrator",
		"modified_by": "Administrator",
		"docstatus": 0,
		"idx": idx,
		"parent": parent,
		"parenttype": parenttype,
		"parentfield": parentfield,
	}
	row.update(values)

	columns = ", ".join("`{0}`".format(key) for key in row)
	placeholders = ", ".join(["%s"] * len(row))
	frappe.db.sql(
		"insert into `tab{0}` ({1}) values ({2})".format(doctype, columns, placeholders),
		list(row.values()),
	)
