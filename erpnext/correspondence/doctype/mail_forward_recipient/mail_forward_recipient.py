from frappe.model.document import Document


class MailForwardRecipient(Document):
	def validate(self):
		self.code = (self.code or "").strip()
		self.email = (self.email or "").strip().lower() or None
