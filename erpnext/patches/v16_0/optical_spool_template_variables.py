"""Make the optical spool limits editable as a table on the template.

The formulas written by `optical_spool_acceptance_formulas` carried the numbers inside the
expression; they now read named variables from the template's Variables table (values from
the quality department's tolerance sheet).
"""

import frappe

TEMPLATE = "Перевірка котушки оптики"
LENGTH_ATTRIBUTE = "Довжина намотки"

# Total attenuation limit per winding length, dB.
MAX_LOSS_BY_LENGTH = {15: 3.5, 20: 4.6, 25: 5.75, 30: 6.9, 40: 9.2}

FORMULAS = {
	"Довжина волокна (км)": (
		"length_km * (1 - length_tolerance_pct / 100) <= reading_1 "
		"<= length_km * (1 + length_tolerance_pct / 100)"
	),
	"Загасання волокна (дБ)": "reading_1 <= (max_loss or loss_per_km * length_km)",
	"Відбиття кінця волокна (дБ)": "reading_1 <= max_reflectance",
}


def execute():
	if not frappe.db.exists("Quality Inspection Template", TEMPLATE):
		return

	from erpnext.patches.setup_custom_fields import create_custom_field_on_qi_template

	frappe.reload_doc("stock", "doctype", "qi_template_variable")
	create_custom_field_on_qi_template()

	template = frappe.get_doc("Quality Inspection Template", TEMPLATE)
	if not template.get("variables"):
		template.append("variables", {"variable": "loss_per_km", "value": 0.23})
		template.append("variables", {"variable": "max_reflectance", "value": -35})
		template.append("variables", {"variable": "length_tolerance_pct", "value": 1})
		for length, limit in MAX_LOSS_BY_LENGTH.items():
			template.append(
				"variables",
				{
					"variable": "max_loss",
					"value": limit,
					"attribute": LENGTH_ATTRIBUTE,
					"attribute_value": f"{length} км",
				},
			)

	for row in template.item_quality_inspection_parameter:
		if row.specification in FORMULAS:
			row.formula_based_criteria = 1
			row.acceptance_formula = FORMULAS[row.specification]

	template.flags.ignore_permissions = True
	template.save()
