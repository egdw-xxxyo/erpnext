"""Move the optical spool limits out of `spool_qc.py` into the Quality Inspection Template.

Length used to be graded by a hardcoded ±1% in the script against a `0..999` template row;
the rows now carry acceptance formulas (see `erpnext.stock.inspection_formula` for the
variables they can use).
"""

import frappe

TEMPLATE = "Перевірка котушки оптики"

FORMULAS = {
	"Довжина волокна (км)": "length_km * 0.99 <= reading_1 <= length_km * 1.01",
	"Загасання волокна (дБ)": "reading_1 <= {15: 3.5}.get(length_km, 0.23 * length_km)",
	"Відбиття кінця волокна (дБ)": "reading_1 <= -35",
}


def execute():
	if not frappe.db.exists("Quality Inspection Template", TEMPLATE):
		return

	rows = frappe.get_all(
		"Item Quality Inspection Parameter",
		filters={"parent": TEMPLATE, "specification": ["in", list(FORMULAS)]},
		fields=["name", "specification"],
	)
	for row in rows:
		frappe.db.set_value(
			"Item Quality Inspection Parameter",
			row.name,
			{"formula_based_criteria": 1, "acceptance_formula": FORMULAS[row.specification]},
			update_modified=False,
		)
