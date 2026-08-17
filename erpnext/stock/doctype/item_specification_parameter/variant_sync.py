"""Push a template's specification parameters onto its existing variants.

`Item.validate()` re-syncs `item_spec_parameters` from the template on every save, so a
variant only learns about a changed template row when something saves it. A variant created
before the template was edited therefore keeps the old rows — and prints the old numbers on
its label — until then. This module saves them all in one go.
"""

import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist()
def resync_template_variants(template, limit=None):
	"""Re-save every variant of `template` so it picks up the template's current spec rows.

	Returns {"updated": [...], "unchanged": [...], "failed": [{"item": ..., "error": ...}]}.
	A variant whose formulas cannot be resolved throws (see `evaluate_spec_formulas`); that
	variant is reported and the others still go through.
	"""
	frappe.has_permission("Item", "write", throw=True)

	variants = frappe.get_all(
		"Item",
		filters={"variant_of": template},
		pluck="name",
		order_by="name",
		limit=cint(limit) or None,
	)

	updated, unchanged, failed = [], [], []

	for name in variants:
		before = _spec_snapshot(name)
		savepoint = "resync_" + frappe.generate_hash(length=8)
		frappe.db.savepoint(savepoint)
		try:
			doc = frappe.get_doc("Item", name)
			doc.save()
		except Exception as e:
			frappe.db.rollback(save_point=savepoint)
			failed.append({"item": name, "error": _clean_error(e)})
			continue

		if _spec_snapshot(name) == before:
			unchanged.append(name)
		else:
			updated.append(name)

	return {"updated": updated, "unchanged": unchanged, "failed": failed}


def _spec_snapshot(item_code):
	rows = frappe.get_all(
		"Item Specification Parameter",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["parameter", "value", "calculated_value", "uom"],
		order_by="idx",
	)
	return [(r.parameter, r.value, r.calculated_value, r.uom) for r in rows]


def _clean_error(exc):
	"""Turn a thrown message into one plain line — the guard's message is HTML."""
	import re

	message = str(getattr(exc, "message", "") or exc)
	message = re.sub(r"<br\s*/?>", " ", message)
	message = re.sub(r"<[^>]+>", "", message)
	return frappe.utils.strip_html(message).strip() or _("Unknown error")
