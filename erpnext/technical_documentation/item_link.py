# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Link the Items that are made to a ЄСКД designation to that designation.

`item_match` puts plausible designations at the top of a person's list. This module does
the opposite job: for the product families whose Item attributes carry the whole
designation — a coil's length and fibre, a battery's cell layout, a ground station's
configuration — the match is exact, so nobody should click 42 batteries one at a time.

A board is deliberately absent. A board designation encodes its coil length and battery
layout («Укропчик 15 FO 25 DAAT» is one of five lengths of the same airframe), and no
Item attribute of the БпЛА template says either, so there is no exact match to make and
guessing one would write a designation the drone was not built to.
"""

import re

import frappe

MODIFICATION_DOCTYPE = "Product Modification"
TYPE_COIL = "Котушка"
TYPE_BATTERY = "Батарея"
TYPE_GROUND_STATION = "НСУ"

# The workbook keeps a УКРП block and a ВРНК (ВАРНЕКС) one for the same product
ORGANIZATION_BY_BRAND = {"Укропчик": "УКРП", "Магура": "ВРНК", "VARNEX": "ВРНК"}
DEFAULT_ORGANIZATION = "УКРП"

ATTRIBUTE_BRAND = "Торгова марка"
ATTRIBUTE_SERIES = "Конфігурація S"
ATTRIBUTE_PARALLEL = "Конфігурація P"
ATTRIBUTE_GS_KIND = "Тип НСУ"

# «НСУ FO аналог, компактная» and «Аналог компактна» are the same station
GS_KIND_KEYS = {
	"аналогкомпактна": "01",
	"аналогрозширена": "11",
	"цифракомпактна": "21",
	"цифрарозширена": "31",
	"аналогцифрарозширена": "41",
}


def _attributes(item):
	rows = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item, "parenttype": "Item"},
		fields=["attribute", "attribute_value"],
	)
	return {row.attribute: (row.attribute_value or "").strip() for row in rows}


def _items_of(modification):
	return frappe.get_all("Item", filters={"specification": modification, "disabled": 0}, pluck="name")


def _organization(attributes):
	return ORGANIZATION_BY_BRAND.get(attributes.get(ATTRIBUTE_BRAND), DEFAULT_ORGANIZATION)


def _modifications(product_type):
	return frappe.get_all(
		MODIFICATION_DOCTYPE,
		filters={"product_type": product_type},
		fields=["name", "modification_code", "full_name", "purpose"],
	)


def _by_organization(modifications):
	grouped = {}
	for row in modifications:
		grouped.setdefault(row.modification_code[:4], {})[row.name] = row
	return grouped


def _coil_key(text):
	"""«Укропчик FO 25 GF» / «VARNEX FO 25 GF» -> `25GF`: the length and the fibre code."""
	match = re.search(r"FO\s+([\d.,]+)\s*([A-Z]{2})\b", text or "")
	if not match:
		return None
	return f"{match.group(1).replace(',', '.')}{match.group(2)}"


def _battery_key(text):
	match = re.search(r"\b(\d+)\s*S\s*(\d+)\s*P\b", (text or "").upper())
	return f"{match.group(1)}S{match.group(2)}P" if match else None


def _gs_key(text):
	"""Fold «аналог, компактная» / «Аналог компактна» / «компактра» onto one key."""
	words = re.findall(r"[а-яіїєґ]+", (text or "").lower())
	folded = []
	for word in words:
		if word.startswith("аналог"):
			folded.append("аналог")
		elif word.startswith("цифр"):
			folded.append("цифра")
		elif word.startswith("компакт"):
			folded.append("компактна")
		elif word.startswith("розшир"):
			folded.append("розширена")
	return "".join(dict.fromkeys(folded)) or None


KEYS = {
	TYPE_COIL: _coil_key,
	TYPE_BATTERY: _battery_key,
	TYPE_GROUND_STATION: _gs_key,
}


def _index(product_type, modifications):
	"""designation key -> modification, per organization prefix."""
	key_of = KEYS[product_type]
	index = {}
	for row in modifications:
		if product_type == TYPE_GROUND_STATION:
			ordinal = row.modification_code.rsplit("-", 1)[-1][:2]
			key = next((k for k, v in GS_KIND_KEYS.items() if v == ordinal), None)
		else:
			key = key_of(row.purpose) or key_of(row.full_name)
		if key:
			index.setdefault(row.modification_code[:4], {}).setdefault(key, row)
	return index


def _item_key(product_type, item, attributes):
	if product_type == TYPE_COIL:
		return _coil_key(item.item_name) or _coil_key(item.name)
	if product_type == TYPE_BATTERY:
		series, parallel = attributes.get(ATTRIBUTE_SERIES), attributes.get(ATTRIBUTE_PARALLEL)
		return _battery_key(f"{series}{parallel}") if series and parallel else None
	return _gs_key(attributes.get(ATTRIBUTE_GS_KIND) or item.item_name)


def link_family(template, product_type, dry_run=True):
	"""Set `specification` on every variant of `template` whose designation is unambiguous."""
	index = _index(product_type, _modifications(product_type))
	variants = frappe.get_all(
		"Item",
		filters={"variant_of": template},
		fields=["name", "item_name", "specification"],
		order_by="name",
	)

	linked, unmatched, already = [], [], []
	for item in variants:
		attributes = _attributes(item.name)
		key = _item_key(product_type, item, attributes)
		row = (index.get(_organization(attributes)) or {}).get(key) if key else None
		if not row:
			unmatched.append((item.name, key))
			continue
		if item.specification == row.name:
			already.append(item.name)
			continue
		linked.append((item.name, row.modification_code))
		if not dry_run:
			frappe.db.set_value(
				"Item",
				item.name,
				{
					"specification": row.name,
					"specification_product_type": product_type,
					"specification_code": frappe.db.get_value(MODIFICATION_DOCTYPE, row.name, "display_code")
					or row.modification_code,
				},
				update_modified=False,
			)

	return {"linked": linked, "unmatched": unmatched, "already_linked": already}


FAMILIES = (
	("OPT-SPOOL", TYPE_COIL),
	("BATT-PACK", TYPE_BATTERY),
	("OPT-GS", TYPE_GROUND_STATION),
)


def run(dry_run=True, families=None):
	"""Link every family. Pass dry_run=False to write."""
	dry_run = bool(dry_run)
	wanted = {name for name in (families or ())} or None
	report = {}
	for template, product_type in FAMILIES:
		if wanted and template not in wanted:
			continue
		if not frappe.db.exists("Item", template):
			report[template] = {"error": "template Item not found"}
			continue
		report[template] = link_family(template, product_type, dry_run=dry_run)

	if not dry_run:
		frappe.db.commit()

	for template, result in report.items():
		if result.get("error"):
			print(f"{template}: {result['error']}")
			continue
		print(
			f"{template}: {len(result['linked'])} linked, "
			f"{len(result['already_linked'])} already, {len(result['unmatched'])} unmatched"
		)
		for item, code in result["linked"]:
			print(f"    {item} -> {code}")
		for item, key in result["unmatched"]:
			print(f"    ! {item} (key {key})")
	print("DRY RUN — nothing written" if dry_run else "LINKS COMMITTED")
	return report


# --- Default kit Items -------------------------------------------------------
#
# A designation is a code, not a part number, so «which Item ships for it» is a separate
# decision from «which Items are made to it». For a battery every cell type answers to
# the same layout code, and for a board no Item answers at all — the airframe Item does
# not carry the coil length the code encodes, the bundle's coil line does. Both are
# recorded as the modification's `default_kit_item`.

# Present for every layout in both the Укропчик and Магура lines, so a kit always resolves
DEFAULT_CELL = "RS55"

BOARD_CAMERA_RE = re.compile(r"\b(DTD|DTA|DD|TD|DA|TA)(?:AF|AT|GF|GT|STHF|STF)?$")
CAMERA_BY_CODE = {
	"DA": "Денна аналогова",
	"TA": "Термальна аналогова",
	"DTA": "Комбіновані Денна та Термальна аналогові",
	"DD": "Денна цифрова",
	"TD": "Термальна цифрова",
	"DTD": "Комбіновані Денна та Термальна цифрові",
}
# «Укропчик 15 FO 25A» — the 463145.106C line names no camera; the workbook calls it denna
BOARD_PLAIN_RE = re.compile(r"^Укропчик\s+(\d+)(\s+FO)?\s+[\d,.]+\s*A$")
BOARD_FAMILY_RE = re.compile(r"^Укропчик\s+(?:Штурм|(\d+))(\s+FO)?\b")
ATTRIBUTE_TU = "Номер ТУ"
ATTRIBUTE_CAMERA = "Тип камери"


def _board_shape(full_name):
	"""«Укропчик 15 FO 25 DTAGF» -> (`БпЛА Укропчик 15 FO`, `Комбіновані ...`)."""
	name = (full_name or "").strip()
	family = BOARD_FAMILY_RE.match(name)
	if not family:
		return None, None
	size, fibre = family.group(1), family.group(2)
	tu = f"БпЛА Укропчик {size}{' FO' if fibre else ''}" if size else "БпЛА Укропчик Штурм"

	if BOARD_PLAIN_RE.match(name):
		return tu, CAMERA_BY_CODE["DA"]
	camera = BOARD_CAMERA_RE.search(name)
	if camera:
		return tu, CAMERA_BY_CODE[camera.group(1)]
	# The 99xx block spells the camera out instead of coding it
	lowered = name.lower()
	digital = "цифров" in lowered
	if "денна + термальна" in lowered or "денна та термальна" in lowered:
		return tu, CAMERA_BY_CODE["DTD" if digital else "DTA"]
	if "термальна" in lowered:
		return tu, CAMERA_BY_CODE["TD" if digital else "TA"]
	if "денна" in lowered:
		return tu, CAMERA_BY_CODE["DD" if digital else "DA"]
	return tu, None


def _airframe_index():
	"""(Номер ТУ, Тип камери) -> the airframe Item, when exactly one answers."""
	index = {}
	for item in frappe.get_all("Item", filters={"variant_of": "BPLA-UKR", "disabled": 0}, pluck="name"):
		attributes = _attributes(item)
		key = (attributes.get(ATTRIBUTE_TU), attributes.get(ATTRIBUTE_CAMERA))
		index.setdefault(key, []).append(item)
	return {key: items[0] for key, items in index.items() if len(items) == 1}


def set_default_kit_items(dry_run=True, boards=None):
	"""Record which Item ships for each battery and board designation."""
	report = {"battery": [], "board": [], "unresolved": []}

	for row in _modifications(TYPE_BATTERY):
		layout = _battery_key(row.purpose) or _battery_key(row.full_name)
		items = [
			name for name in _items_of(row.name) if name.endswith(DEFAULT_CELL) or f"-{DEFAULT_CELL}" in name
		]
		if not layout or len(items) != 1:
			report["unresolved"].append((row.modification_code, layout, len(items)))
			continue
		report["battery"].append((row.modification_code, items[0]))
		if not dry_run:
			frappe.db.set_value(
				MODIFICATION_DOCTYPE, row.name, "default_kit_item", items[0], update_modified=False
			)

	airframes = _airframe_index()
	for row in _modifications("БпЛА"):
		if boards and row.modification_code not in boards:
			continue
		item = airframes.get(_board_shape(row.full_name))
		if not item:
			report["unresolved"].append((row.modification_code, row.full_name, 0))
			continue
		report["board"].append((row.modification_code, item))
		if not dry_run:
			frappe.db.set_value(
				MODIFICATION_DOCTYPE, row.name, "default_kit_item", item, update_modified=False
			)

	if not dry_run:
		frappe.db.commit()

	for kind in ("battery", "board"):
		print(f"{kind}: {len(report[kind])}")
		for code, item in report[kind]:
			print(f"    {code} -> {item}")
	print(f"unresolved: {len(report['unresolved'])}")
	for code, detail, count in report["unresolved"]:
		print(f"    ! {code} ({detail}, {count} candidates)")
	print("DRY RUN — nothing written" if dry_run else "DEFAULTS COMMITTED")
	return report
