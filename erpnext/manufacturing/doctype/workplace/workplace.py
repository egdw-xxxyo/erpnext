import frappe
from frappe import _
from frappe.model.document import Document


class Workplace(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.manufacturing.doctype.workplace_employee.workplace_employee import WorkplaceEmployee
		from erpnext.manufacturing.doctype.workplace_operation.workplace_operation import (
			WorkplaceOperation,
		)
		from erpnext.manufacturing.doctype.workplace_printer.workplace_printer import WorkplacePrinter

		allowed_employees: DF.Table["WorkplaceEmployee"]
		allowed_operations: DF.Table["WorkplaceOperation"]
		barcode: DF.Data | None
		company: DF.Link | None
		description: DF.SmallText | None
		is_active: DF.Check
		printers: DF.Table["WorkplacePrinter"]
		short_name: DF.Data | None
		workplace_name: DF.Data | None

	def before_insert(self):
		if not self.barcode:
			self.barcode = f"WP-{frappe.generate_hash(length=8).upper()}"

	def validate(self):
		self._validate_printers()

	def _validate_printers(self):
		if not self.printers:
			return
		seen = set()
		default_count = 0
		for row in self.printers:
			if row.label_printer in seen:
				frappe.throw(_("Printer {0} is listed more than once").format(row.label_printer))
			seen.add(row.label_printer)
			if row.is_default:
				default_count += 1
		if default_count > 1:
			frappe.throw(_("Only one printer can be marked as Default"))
