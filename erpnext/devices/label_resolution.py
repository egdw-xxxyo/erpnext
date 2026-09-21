"""Resolve which Label Template to print for an item and a given purpose.

`Item.label_templates` (child table `Item Label Template`) carries a free-text `purpose`
column — "Passed" / "Failed" — so one item can declare a different label per QC outcome.
Nothing read that column before this module; `get_label_templates_for_items` in
`purchase_receipt_utils.py` deliberately returns every row regardless of purpose because
its callers render a picker for a human.

Lookup order for a purpose-specific label:
  1. `Item Label Template` rows on the item itself
  2. the same rows on the item's variant template (variants rarely repeat the config)
  3. `OTDR Configuration.passed_label_template` / `failed_label_template` as a site-wide default
"""

import frappe

PURPOSE_PASSED = "Passed"
PURPOSE_FAILED = "Failed"

_CONFIG_FIELD_BY_PURPOSE = {
	PURPOSE_PASSED: "passed_label_template",
	PURPOSE_FAILED: "failed_label_template",
}


def _rows_for(item_code, purpose):
	"""Label rows on `item_code` whose purpose matches, case- and space-insensitively."""
	rows = frappe.get_all(
		"Item Label Template",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["label_template", "label_printer", "purpose"],
		order_by="idx",
	)
	wanted = (purpose or "").strip().casefold()
	return [r for r in rows if (r.purpose or "").strip().casefold() == wanted]


def resolve_label_template(item_code, purpose, otdr_configuration=None):
	"""Return {"label_template", "label_printer", "source"} for `purpose`, or None.

	`source` records which of the three tiers answered, purely so callers can log it.
	"""
	if not item_code or not purpose:
		return None

	rows = _rows_for(item_code, purpose)
	source = "item"

	if not rows:
		template_item = frappe.db.get_value("Item", item_code, "variant_of")
		if template_item:
			rows = _rows_for(template_item, purpose)
			source = "variant_of"

	if rows:
		row = rows[0]
		return {
			"label_template": row.label_template,
			"label_printer": row.label_printer,
			"source": source,
		}

	config_field = _CONFIG_FIELD_BY_PURPOSE.get(purpose)
	if config_field and otdr_configuration:
		label_template = frappe.db.get_value("OTDR Configuration", otdr_configuration, config_field)
		if label_template:
			return {
				"label_template": label_template,
				"label_printer": None,
				"source": "otdr_configuration",
			}

	return None
