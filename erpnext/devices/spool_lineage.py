"""Stamp each produced optical spool with the fiber reel it was wound from.

The lineage is already implicit in the Manufacture Stock Entry — the consumed row names a
Batch, the produced row names Serial Nos — but answering "which reel, and whose fiber, made
this rejected spool" from that requires walking Stock Entry -> Serial and Batch Bundle ->
Batch for every candidate entry. Denormalising the reel onto the Serial No turns that into a
single read, and makes the reverse question ("which spools came off this reel") a plain list
filter.

Wired as a `Stock Entry.on_submit` doc_event so no stock file is edited.
"""

import frappe

RELEVANT_PURPOSES = ("Manufacture", "Repack")


def _bundle_batches(bundle_name):
	"""Distinct batches in a bundle, with the quantity drawn from each."""
	rows = frappe.get_all(
		"Serial and Batch Entry",
		filters={"parent": bundle_name, "parenttype": "Serial and Batch Bundle"},
		fields=["batch_no", "qty"],
	)
	totals = {}
	for row in rows:
		if row.batch_no:
			totals[row.batch_no] = totals.get(row.batch_no, 0) + abs(row.qty or 0)
	return totals


def _bundle_serials(bundle_name):
	return frappe.get_all(
		"Serial and Batch Entry",
		filters={"parent": bundle_name, "parenttype": "Serial and Batch Bundle"},
		pluck="serial_no",
	)


def stamp_source_batch(doc, method=None):
	"""Copy the consumed reel's batch (and its supplier) onto the produced serials."""
	if doc.purpose not in RELEVANT_PURPOSES:
		return

	consumed_batches = {}
	produced_serials = []

	for row in doc.items:
		if not row.serial_and_batch_bundle:
			continue

		if row.get("is_finished_item") and row.t_warehouse:
			produced_serials.extend(s for s in _bundle_serials(row.serial_and_batch_bundle) if s)
		elif row.s_warehouse:
			for batch_no, qty in _bundle_batches(row.serial_and_batch_bundle).items():
				consumed_batches[batch_no] = consumed_batches.get(batch_no, 0) + qty

	if not produced_serials or not consumed_batches:
		return

	if len(consumed_batches) > 1:
		# Guessing which reel fed which spool would put a wrong producer on a real
		# traceability record, so record nothing and say why.
		frappe.log_error(
			title="Spool lineage ambiguous",
			message=(
				f"Stock Entry {doc.name} consumed {len(consumed_batches)} batches "
				f"({', '.join(sorted(consumed_batches))}) while producing "
				f"{len(produced_serials)} serials, so no source batch was stamped. "
				"Use one reel per manufacturing entry to keep lineage unambiguous."
			),
		)
		return

	batch_no = next(iter(consumed_batches))
	supplier = frappe.db.get_value("Batch", batch_no, "supplier")

	for serial_no in produced_serials:
		frappe.db.set_value(
			"Serial No",
			serial_no,
			{"source_batch_no": batch_no, "source_reel_supplier": supplier},
			update_modified=False,
		)
