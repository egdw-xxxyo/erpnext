"""Patch script to add early serial number generation to stock purchase_receipt.py.

This script patches the STOCK purchase_receipt.py inside the Docker container.
It appends a before_save hook for early serial number generation.
"""
import os
import re
import stat

PR_PY = "/home/frappe/frappe-bench/apps/erpnext/erpnext/stock/doctype/purchase_receipt/purchase_receipt.py"
MARKER = "def _generate_serials_on_save"

METHODS_CODE = '''

	def before_save(self):
		if hasattr(super(), 'before_save'):
			super().before_save()
		self._generate_serials_on_save()

	def _generate_serials_on_save(self):
		"""Generate serial numbers for items with has_serial_no=1 at save time (before submit)."""
		if self.docstatus != 0:
			return
		if self.is_return:
			return
		if not self.name or self.name.startswith("new-"):
			return

		import frappe as _frappe

		for item in self.items:
			if item.serial_and_batch_bundle:
				continue

			item_details = _frappe.get_cached_value(
				"Item", item.item_code,
				["has_serial_no", "serial_no_series", "serial_number_template"],
				as_dict=True
			)
			if not item_details or not item_details.has_serial_no:
				continue
			if not item_details.serial_no_series:
				continue

			serial_no_series = item_details.serial_no_series
			if item_details.serial_number_template and "{ATTR:" in (serial_no_series or ""):
				try:
					from erpnext.stock.doctype.serial_number_template.serial_number_template import (
						resolve_series_for_item,
					)
					serial_no_series = resolve_series_for_item(
						item_details.serial_number_template, item.item_code
					)
				except Exception:
					pass

			qty = item.qty or item.received_qty or 0
			if qty <= 0:
				continue

			from erpnext.stock.serial_batch_bundle import SerialBatchCreation

			try:
				sbc = SerialBatchCreation({
					"item_code": item.item_code,
					"warehouse": item.warehouse,
					"voucher_type": "Purchase Receipt",
					"voucher_no": "",
					"posting_date": self.posting_date,
					"posting_time": self.posting_time,
					"company": self.company,
					"qty": qty,
					"total_qty": qty,
					"type_of_transaction": "Inward",
					"serial_no_series": serial_no_series,
					"do_not_submit": True,
					"ignore_sabb_validation": True,
				})
				bundle = sbc.make_serial_and_batch_bundle()
				if bundle and bundle.name:
					_frappe.db.set_value("Serial and Batch Bundle", bundle.name, "voucher_no", self.name)
					item.serial_and_batch_bundle = bundle.name
					item.use_serial_batch_fields = 0
			except Exception as e:
				_frappe.log_error(
					title="PR Serial Generation Error",
					message=f"Item {item.item_code}: {str(e)}"
				)
'''

with open(PR_PY, "r") as f:
    content = f.read()

if MARKER in content:
    print("[purchase_receipt_patch] Patch already applied, skipping")
else:
    validate_match = re.search(r'(\n\tdef validate\(self\):)', content)
    if validate_match:
        insert_pos = validate_match.start()
        content = content[:insert_pos] + METHODS_CODE + content[insert_pos:]

        try:
            os.chmod(PR_PY, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
        except OSError:
            pass

        with open(PR_PY, "w") as f:
            f.write(content)
        print("[purchase_receipt_patch] Injected before_save and helper methods")
    else:
        print("[purchase_receipt_patch] ERROR: Could not find 'def validate(self):' in purchase_receipt.py")
        exit(1)

print("[purchase_receipt_patch] Done")
