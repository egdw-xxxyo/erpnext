"""Ставки зарплатних податків — одне місце, звідки їх читають листок, аванс і відомість.

Ставки міняє закон, а не програміст, тож вони лежать у налаштуваннях, а не в коді. Пільгова
ставка ЄСВ застосовується до працівника з групою інвалідності — див. `erpnext.hr.payroll_tax`.
"""

import frappe
from frappe.model.document import Document


class PayrollTaxSettings(Document):
	def on_update(self):
		frappe.clear_cache(doctype="Payroll Tax Settings")
