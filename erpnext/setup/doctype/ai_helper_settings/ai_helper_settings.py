import frappe
from frappe import _
from frappe.model.document import Document


class AIHelperSettings(Document):
	def validate(self):
		seen = set()
		for row in self.company_keys:
			company = row.company or ""
			if company in seen:
				frappe.throw(
					_("Row #{0}: {1} already has a key").format(row.idx, company or _("the default key"))
				)
			seen.add(company)
