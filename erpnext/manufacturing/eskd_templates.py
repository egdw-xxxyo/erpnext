"""Templates behind the ЄСКД catalogs.

Every designation in the workbook is assembled, not typed: the board code
`УКРП.200121.1501210013С` is organisation `УКРП`, drone class `200121`, frame `15`,
camera `01`, then the catalog position of the battery (`21`) and of the coil (`0013`).
This module defines the Item Attributes, the Specification Number Templates that spell
that out, and the Specification templates whose variants resolve their own code.

Idempotent — safe to re-run; existing rows are updated in place.
"""

import frappe

ORGANISATION = "Організація ЄСКД"
DRONE_CLASS = "Клас дрона"
FRAME_SIZE = "Типорозмір рами"
CAMERA_TYPE = "Тип камери"

ATTRIBUTES = {
	ORGANISATION: [
		("Укропчик", "УКРП"),
		("VARNEX", "ВРНК"),
	],
	DRONE_CLASS: [
		("Оптичний", "200121"),
		("Радіокерований", "463145"),
	],
	FRAME_SIZE: [
		("7 дюймів", "07"),
		("8 дюймів", "08"),
		("10 дюймів", "10"),
		("13 дюймів", "13"),
		("15 дюймів", "15"),
		("23 дюйма", "23"),
		# The workbook keeps a second Укропчик 10 block on a different frame ("іньша рама"),
		# numbered 99 because the frame itself has no size code yet.
		("Інша рама", "99"),
	],
	CAMERA_TYPE: [
		("Денна (сутінкова) аналогова", "01"),
		("Термальна аналогова", "02"),
		("Денна (сутінкова) + термальна аналогова", "03"),
		("Денна (сутінкова) цифрова", "04"),
		("Термальна цифрова", "05"),
		("Денна (сутінкова) + термальна цифрова", "06"),
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


NUMBER_TEMPLATES = {
	"ЄСКД БпЛА": [
		_abbr(ORGANISATION),
		_literal("."),
		_abbr(DRONE_CLASS),
		_literal("."),
		_abbr(FRAME_SIZE),
		_abbr(CAMERA_TYPE),
		_linked_ordinal(ROLE_BATTERY, 2),
		_linked_ordinal(ROLE_COIL, 4),
		_literal("С"),
	],
	"ЄСКД Котушка": [
		_abbr(ORGANISATION),
		_literal(".200121.002-"),
		_ordinal(2),
		_literal("С"),
	],
	"ЄСКД Батарея": [
		_abbr(ORGANISATION),
		_literal(".563562.001-"),
		_ordinal(2),
		_literal("С"),
	],
	"ЄСКД НСУ": [
		_abbr(ORGANISATION),
		_literal(".563562.003-"),
		_ordinal(2),
		_literal("С"),
	],
}

# Specification template -> (kind, number template, variant attributes, name pattern)
SPECIFICATION_TEMPLATES = {
	"Специфікація БпЛА": (
		"Board",
		"ЄСКД БпЛА",
		[ORGANISATION, DRONE_CLASS, FRAME_SIZE, CAMERA_TYPE],
	),
	"Специфікація котушки": ("Coil", "ЄСКД Котушка", [ORGANISATION]),
	"Специфікація батареї": ("Battery", "ЄСКД Батарея", [ORGANISATION]),
	"Специфікація НСУ": ("Ground Station", "ЄСКД НСУ", [ORGANISATION]),
	# A БпАК has no designation of its own — it is a numbered modification pairing a
	# drone with a ground station, so it carries components but no number template.
	"Специфікація БпАК": ("BpAK", None, [ORGANISATION]),
}

TEMPLATE_BY_KIND = {kind: name for name, (kind, _t, _a) in SPECIFICATION_TEMPLATES.items()}


def setup():
	"""Create (or refresh) the attributes and templates the ЄСКД catalogs are built on."""
	for role, kind in COMPONENT_ROLES.items():
		_ensure_role(role, kind)
	for attribute, values in ATTRIBUTES.items():
		_ensure_attribute(attribute, values)
	for template, components in NUMBER_TEMPLATES.items():
		_ensure_number_template(template, components)
	frappe.clear_cache(doctype="Specification Number Template")
	for template, (kind, number_template, attributes) in SPECIFICATION_TEMPLATES.items():
		_ensure_specification_template(template, kind, number_template, attributes)


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
	for value, abbr in values:
		if value in existing:
			existing[value].abbr = abbr
		else:
			doc.append("item_attribute_values", {"attribute_value": value, "abbr": abbr})
	doc.save(ignore_permissions=True)
	return doc.name


def _ensure_number_template(template, components):
	if frappe.db.exists("Specification Number Template", template):
		doc = frappe.get_doc("Specification Number Template", template)
	else:
		doc = frappe.new_doc("Specification Number Template")
		doc.template_name = template

	doc.set("components", [])
	for component in components:
		doc.append("components", component)
	doc.save(ignore_permissions=True)
	return doc.name


def _ensure_specification_template(template, kind, number_template, attributes):
	if frappe.db.exists("Specification", template):
		doc = frappe.get_doc("Specification", template)
	else:
		doc = frappe.new_doc("Specification")
		doc.specification_name = template
		doc.specification_code = template

	doc.has_variants = 1
	doc.specification_kind = kind
	if number_template:
		doc.specification_number_template = number_template

	present = {row.attribute for row in doc.get("attributes") or []}
	for attribute in attributes:
		if attribute not in present:
			doc.append("attributes", {"attribute": attribute})
	doc.save(ignore_permissions=True)
	return doc.name
