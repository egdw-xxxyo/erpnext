from frappe.model.document import Document

from erpnext.access_control import company_access


class UserCompanyAccess(Document):
	def validate(self):
		company_access.validate_access(self)

	def on_update(self):
		company_access.report_sync(company_access.sync_user(self.user))

	def on_trash(self):
		company_access.report_sync(company_access.apply(self.user, [], None))
