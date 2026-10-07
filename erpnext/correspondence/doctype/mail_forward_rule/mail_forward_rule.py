import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.correspondence.mail_routing import matches, parse_patterns


class MailForwardRule(Document):
	def validate(self):
		patterns = parse_patterns(self.sender_patterns)
		if not patterns:
			frappe.throw(_("Add at least one part of a sender address"))
		self.sender_patterns = "\n".join(patterns)
		self.validate_own_addresses(patterns)
		self.validate_recipients()

	def validate_own_addresses(self, patterns):
		from erpnext.correspondence.mail_forward import own_addresses

		clashes = sorted(address for address in own_addresses() if matches(patterns, address))
		if clashes:
			frappe.throw(
				_("The rule would match our own addresses and could forward in a loop: {0}").format(
					", ".join(clashes)
				)
			)

	def validate_recipients(self):
		codes = [row.recipient for row in self.recipients]
		if not codes:
			frappe.throw(_("Choose at least one recipient"))
		self.set(
			"recipients",
			[row for index, row in enumerate(self.recipients) if row.recipient not in codes[:index]],
		)
