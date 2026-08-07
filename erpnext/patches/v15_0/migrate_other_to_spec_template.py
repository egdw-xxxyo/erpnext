import frappe

TEMPLATES = [
	{
		"item_template": "BATT-PACK",
		"spec_name": "Battery Pack Spec",
		"description": "Battery: УКРП.563562.001-{code}С",
		"components": [
			{"component_type": "Literal", "value": "УКРП.563562.001-"},
			{"component_type": "Item Attribute Abbr", "attribute_link": "Battery шифр код"},
			{"component_type": "Literal", "value": "С"},
		],
	},
	{
		"item_template": "OPT-SPOOL",
		"spec_name": "FO Spool Spec",
		"description": "FO spool: УКРП.200121.002-{code}С",
		"components": [
			{"component_type": "Literal", "value": "УКРП.200121.002-"},
			{"component_type": "Item Attribute Abbr", "attribute_link": "FO шифр код"},
			{"component_type": "Literal", "value": "С"},
		],
	},
	{
		"item_template": "OPT-GS",
		"spec_name": "NSU FO Spec",
		"description": "NSU: УКРП.563562.003-{code}С",
		"components": [
			{"component_type": "Literal", "value": "УКРП.563562.003-"},
			{"component_type": "Item Attribute Abbr", "attribute_link": "НСУ шифр код"},
			{"component_type": "Literal", "value": "С"},
		],
	},
]


def execute():
	for cfg in TEMPLATES:
		if not frappe.db.exists("Item", cfg["item_template"]):
			continue
		_ensure_spec_template(cfg)
		_link_on_item_template(cfg["item_template"], cfg["spec_name"])
		_resave_variants(cfg["item_template"])
	frappe.db.commit()


def _ensure_spec_template(cfg):
	if frappe.db.exists("Specification Number Template", cfg["spec_name"]):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Specification Number Template",
			"template_name": cfg["spec_name"],
			"description": cfg["description"],
			"components": cfg["components"],
		}
	)
	doc.insert(ignore_permissions=True)


def _link_on_item_template(item_template, spec_name):
	frappe.db.set_value(
		"Item", item_template, "specification_number_template", spec_name, update_modified=False
	)


def _resave_variants(item_template):
	for variant in frappe.get_all("Item", filters={"variant_of": item_template}, pluck="name"):
		try:
			doc = frappe.get_doc("Item", variant)
			doc.save(ignore_permissions=True)
		except Exception as e:
			print(f"  WARN failed to resave {variant}: {e}")
