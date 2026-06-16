import frappe


def execute():
	"""Backfill Pallet.sales_order from Package.pallet -> Package.sales_order.
	Tag existing SO Items as Direct if source_type is null."""
	if not frappe.db.has_column("Pallet", "sales_order"):
		return

	rows = frappe.db.sql(
		"""
		SELECT pallet, sales_order
		FROM `tabPackage`
		WHERE pallet IS NOT NULL AND pallet != ''
		  AND sales_order IS NOT NULL AND sales_order != ''
		  AND docstatus < 2
		GROUP BY pallet, sales_order
		""",
		as_dict=True,
	)
	by_pallet = {}
	for r in rows:
		by_pallet.setdefault(r.pallet, set()).add(r.sales_order)

	for pallet, sos in by_pallet.items():
		if len(sos) != 1:
			continue
		so = next(iter(sos))
		existing = frappe.db.get_value("Pallet", pallet, "sales_order")
		if existing:
			continue
		frappe.db.set_value("Pallet", pallet, "sales_order", so, update_modified=False)

	if frappe.db.has_column("Sales Order Item", "source_type"):
		frappe.db.sql(
			"""UPDATE `tabSales Order Item`
			   SET source_type='Direct'
			   WHERE source_type IS NULL OR source_type = ''"""
		)

	frappe.db.commit()
