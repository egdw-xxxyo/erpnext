from frappe.model.document import Document

from erpnext.access_control import company_access


class CompanyAccessScope(Document):
	def validate(self):
		company_access.validate_scope(self)

	def on_update(self):
		company_access.report_sync(company_access.sync_scope(self.name))
