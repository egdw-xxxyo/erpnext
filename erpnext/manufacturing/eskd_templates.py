"""Templates behind the ЄСКД catalogs.

Every designation in the workbook is assembled, not typed: the board code
`УКРП.200121.1501210013С` is organisation `УКРП`, drone class `200121`, frame `15`,
camera `01`, then the catalog position of the battery (`21`) and of the coil (`0013`).
This module defines the Item Attributes, the Specification Number Templates that spell
that out, and the Specification templates whose variants resolve their own code.

Idempotent — safe to re-run; existing rows are updated in place.
"""

import frappe

# The brand an item carries is the ЄСКД organisation: Укропчик designations start with
# УКРП, Варнекс ones with ВРНК. The attribute belongs to the Item catalog, so its
# abbreviation (U / V, used in item codes) is left alone — the designation prefix comes
# from the Attribute Value Map on the number template, the readable short name from the
# attribute itself, and both are editable in the desk.
TRADE_MARK = "Торгова марка"
ORGANISATION_SHORT_NAMES = {"Укропчик": "УКРП", "Варнекс": "ВРНК"}

DRONE_CLASS = "Клас дрона"
FRAME_SIZE = "Типорозмір рами"
CAMERA_TYPE = "Тип камери"
# Battery cells are already described by two attributes maintained outside ЄСКД —
# reuse them instead of introducing a combined "6S3P" attribute of our own.
BATTERY_SERIES = "Конфігурація S"
BATTERY_PARALLEL = "Конфігурація P"
COIL_TYPE = "Тип котушки"
GS_SIGNAL = "Тип сигналу НСУ"
GS_FORM = "Виконання НСУ"

# attribute -> [(value, abbr, short name used in generated specification names)]
# Торгова марка is not here: it belongs to the Item catalog and is only read from.
ATTRIBUTES = {
	DRONE_CLASS: [
		("Оптичний", "200121", "FO"),
		("Радіокерований", "463145", "RC"),
	],
	FRAME_SIZE: [
		("7 дюймів", "07", "7"),
		("8 дюймів", "08", "8"),
		("10 дюймів", "10", "10"),
		("13 дюймів", "13", "13"),
		("15 дюймів", "15", "15"),
		("23 дюйма", "23", "23"),
		# The workbook keeps a second Укропчик 10 block on a different frame ("іньша рама"),
		# numbered 99 because the frame itself has no size code yet.
		("Інша рама", "99", "X"),
	],
	CAMERA_TYPE: [
		("Денна (сутінкова) аналогова", "01", "DA"),
		("Термальна аналогова", "02", "TA"),
		("Денна (сутінкова) + термальна аналогова", "03", "DTA"),
		("Денна (сутінкова) цифрова", "04", "DD"),
		("Термальна цифрова", "05", "TD"),
		("Денна (сутінкова) + термальна цифрова", "06", "DTD"),
	],
	# The abbreviation of a catalog attribute is its position in the workbook table, so
	# picking "125 0,25 5 км" already tells you the specification is number 11.
	COIL_TYPE: [
		("ДШВ 1 км", "01", "FO 1 ST"),
		("ДШВ 1,5 км", "02", "FO 1.5 ST"),
		("ДШВ 2 км", "03", "FO 2 ST"),
		("125 0,25 5 км", "11", "FO 5 AF"),
		("125 0,25 10 км", "12", "FO 10 AF"),
		("125 0,25 15 км", "13", "FO 15 AF"),
		("125 0,2 20 км", "21", "FO 20 AT"),
		("125 0,2 25 км", "22", "FO 25 AT"),
		("150 0,25 15 км", "31", "FO 15 GF"),
		("150 0,25 20 км", "32", "FO 20 GF"),
		("150 0,25 25 км", "33", "FO 25 GF"),
		("150 0,2 30 км", "41", "FO 30 GT"),
		("150 0,2 40 км", "42", "FO 40 GT"),
	],
	GS_SIGNAL: [
		("Аналогова", "A", "аналог"),
		("Цифрова", "D", "цифра"),
	],
	GS_FORM: [
		("Компактна", "K", "компактна"),
		("Розширена", "R", "розширена"),
	],
}


ROLE_COIL = "Котушка"
ROLE_BATTERY = "Батарея"
ROLE_BOARD = "Борт"
ROLE_GROUND_STATION = "НСУ"

COMPONENT_ROLES = {
	ROLE_COIL: "Coil",
	ROLE_BATTERY: "Battery",
	ROLE_BOARD: "Board",
	ROLE_GROUND_STATION: "Ground Station",
}


def _literal(value):
	return {"component_type": "Literal", "value": value}


def _abbr(attribute):
	return {"component_type": "Item Attribute Abbr", "attribute_link": attribute}


def _ordinal(digits=2):
	return {"component_type": "Ordinal", "ordinal_digits": digits}


def _linked_ordinal(role, digits=2):
	return {
		"component_type": "Specification Ordinal",
		"component_role": role,
		"ordinal_digits": digits,
	}


def _short_name(attribute):
	return {"component_type": "Item Attribute Short Name", "attribute_link": attribute}


# Every ЄСКД designation opens with the organisation, and which organisation it is comes
# from the brand on the item. The pairing is data on the template (Attribute Value Map),
# not code — add a brand there and its designations start working.
ORGANISATION_MAP = [
	{"attribute": TRADE_MARK, "attribute_value": "Укропчик", "mapped_value": "УКРП"},
	{"attribute": TRADE_MARK, "attribute_value": "Варнекс", "mapped_value": "ВРНК"},
]

NUMBER_TEMPLATES = {
	"ЄСКД БпЛА": {
		"components": [
			_short_name(TRADE_MARK),
			_literal("."),
			_abbr(DRONE_CLASS),
			_literal("."),
			_abbr(FRAME_SIZE),
			_abbr(CAMERA_TYPE),
			_linked_ordinal(ROLE_BATTERY, 2),
			_linked_ordinal(ROLE_COIL, 4),
			_literal("С"),
		],
		"value_map": ORGANISATION_MAP,
	},
	"ЄСКД Котушка": {
		"components": [
			_short_name(TRADE_MARK),
			_literal(".200121.002-"),
			_ordinal(2),
			_literal("С"),
		],
		"value_map": ORGANISATION_MAP,
	},
	"ЄСКД Батарея": {
		"components": [
			_short_name(TRADE_MARK),
			_literal(".563562.001-"),
			_ordinal(2),
			_literal("С"),
		],
		"value_map": ORGANISATION_MAP,
	},
	"ЄСКД НСУ": {
		"components": [
			_short_name(TRADE_MARK),
			_literal(".563562.003-"),
			_ordinal(2),
			_literal("С"),
		],
		"value_map": ORGANISATION_MAP,
	},
}

CHEMISTRY = "Хімія"

# Each template says which ЄСКД catalog it feeds, how its designation is built, which
# attributes describe a variant — `(attribute, fixed value)`, where a fixed value is
# pinned for the whole catalog and never asked for — and which Item template the catalog
# describes, so a specification always points at the group of Items it covers.
#
# The name pattern is resolved on save from the short names of the picked attributes,
# `{ORDINAL}` for the catalog position and `{Role}` for a child specification — so a
# variant is described by what it is made of, never by hand-typed text.
SPECIFICATION_TEMPLATES = {
	"Специфікація БпЛА": {
		"kind": "Board",
		"number_template": "ЄСКД БпЛА",
		"attributes": [
			(TRADE_MARK, None),
			(DRONE_CLASS, None),
			(FRAME_SIZE, None),
			(CAMERA_TYPE, None),
		],
		"name_pattern": (
			f"{{{TRADE_MARK}}} {{{FRAME_SIZE}}} {{{CAMERA_TYPE}}}: {{{ROLE_COIL}}} / {{{ROLE_BATTERY}}}"
		),
	},
	"Специфікація котушки": {
		"kind": "Coil",
		"number_template": "ЄСКД Котушка",
		"attributes": [(TRADE_MARK, None), (COIL_TYPE, None)],
		"name_pattern": f"{{{COIL_TYPE}}} ({{{TRADE_MARK}}}-{{ORDINAL}})",
	},
	# УКРП.563562.001-ХХ covers Li-ion packs up to 50 V, so the chemistry is pinned and
	# only the cell layout varies.
	"Специфікація батареї": {
		"kind": "Battery",
		"number_template": "ЄСКД Батарея",
		"item_template": "BATT-PACK",
		"attributes": [
			(TRADE_MARK, None),
			(CHEMISTRY, "Li-ion"),
			(BATTERY_SERIES, None),
			(BATTERY_PARALLEL, None),
		],
		"name_pattern": f"{{{BATTERY_SERIES}}}{{{BATTERY_PARALLEL}}} ({{{TRADE_MARK}}}-{{ORDINAL}})",
	},
	"Специфікація НСУ": {
		"kind": "Ground Station",
		"number_template": "ЄСКД НСУ",
		"attributes": [(TRADE_MARK, None), (GS_SIGNAL, None), (GS_FORM, None)],
		"name_pattern": f"НСУ {{{GS_SIGNAL}}} {{{GS_FORM}}} ({{{TRADE_MARK}}}-{{ORDINAL}})",
	},
	# A БпАК has no designation of its own — it is a numbered modification pairing a
	# drone with a ground station, so it carries components but no number template.
	"Специфікація БпАК": {
		"kind": "BpAK",
		"number_template": None,
		"attributes": [(TRADE_MARK, None)],
		"name_pattern": f"БпАК {{ORDINAL}}: {{{ROLE_BOARD}}} / {{{ROLE_GROUND_STATION}}}",
	},
}

TEMPLATE_BY_KIND = {config["kind"]: name for name, config in SPECIFICATION_TEMPLATES.items()}


def setup():
	"""Create (or refresh) the attributes and templates the ЄСКД catalogs are built on."""
	for role, kind in COMPONENT_ROLES.items():
		_ensure_role(role, kind)
	for attribute, values in ATTRIBUTES.items():
		_ensure_attribute(attribute, values)
	_ensure_short_names(TRADE_MARK, ORGANISATION_SHORT_NAMES)
	for template, config in NUMBER_TEMPLATES.items():
		_ensure_number_template(template, config)
	frappe.clear_cache(doctype="Specification Number Template")
	for template, config in SPECIFICATION_TEMPLATES.items():
		_ensure_specification_template(template, config)


def _ensure_role(role, kind):
	if frappe.db.exists("Specification Component Role", role):
		doc = frappe.get_doc("Specification Component Role", role)
	else:
		doc = frappe.new_doc("Specification Component Role")
		doc.role_name = role
	doc.specification_kind = kind
	doc.save(ignore_permissions=True)
	return doc.name


def _ensure_attribute(attribute, values):
	if frappe.db.exists("Item Attribute", attribute):
		doc = frappe.get_doc("Item Attribute", attribute)
	else:
		doc = frappe.new_doc("Item Attribute")
		doc.attribute_name = attribute

	existing = {row.attribute_value: row for row in doc.get("item_attribute_values") or []}
	for value, abbr, short_name in values:
		if value in existing:
			existing[value].abbr = abbr
			existing[value].short_name = short_name
		else:
			doc.append(
				"item_attribute_values",
				{"attribute_value": value, "abbr": abbr, "short_name": short_name},
			)
	doc.save(ignore_permissions=True)
	return doc.name


def _ensure_short_names(attribute, short_names):
	"""Fill in short names on an attribute owned by someone else, without overwriting."""
	if not frappe.db.exists("Item Attribute", attribute):
		return
	doc = frappe.get_doc("Item Attribute", attribute)
	changed = False
	for row in doc.get("item_attribute_values") or []:
		short_name = short_names.get(row.attribute_value)
		if short_name and not row.short_name:
			row.short_name = short_name
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_number_template(template, config):
	if frappe.db.exists("Specification Number Template", template):
		doc = frappe.get_doc("Specification Number Template", template)
	else:
		doc = frappe.new_doc("Specification Number Template")
		doc.template_name = template

	doc.set("components", [])
	for component in config["components"]:
		doc.append("components", component)

	existing = {(row.attribute, row.attribute_value) for row in doc.get("value_map") or []}
	for row in config.get("value_map") or []:
		if (row["attribute"], row["attribute_value"]) not in existing:
			doc.append("value_map", row)
	doc.save(ignore_permissions=True)
	return doc.name


def _ensure_specification_template(template, config):
	if frappe.db.exists("Specification", template):
		doc = frappe.get_doc("Specification", template)
	else:
		doc = frappe.new_doc("Specification")
		doc.specification_name = template
		doc.specification_code = template

	doc.has_variants = 1
	doc.specification_kind = config["kind"]
	if config.get("number_template"):
		doc.specification_number_template = config["number_template"]
	if config.get("name_pattern"):
		doc.variant_name_pattern = config["name_pattern"]
	# The Item template is site data — a bench without that Item keeps the catalog loose.
	item_template = config.get("item_template")
	if item_template and frappe.db.exists("Item", item_template):
		doc.item_template = item_template

	wanted = dict(config["attributes"])
	doc.set("attributes", [row for row in doc.get("attributes") or [] if row.attribute in wanted])
	rows = {row.attribute: row for row in doc.get("attributes")}
	for attribute, fixed_value in config["attributes"]:
		if attribute in rows:
			rows[attribute].attribute_value = fixed_value
		else:
			doc.append("attributes", {"attribute": attribute, "attribute_value": fixed_value})
	doc.save(ignore_permissions=True)
	return doc.name
