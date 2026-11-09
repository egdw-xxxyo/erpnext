"""Keep the internal support coordinator separate from the customer's contact."""

from email.utils import parseaddr

import frappe


class SupportRequestIntake:
	def set_lead_contact(self, email_id):
		email = parseaddr(email_id or "")[1]
		user = frappe.db.get_value("User", email, "name") if email else None
		staff_roles = {"Support Team", "Repair Support", "System Manager"}
		internal_sender = user and (
			user == "Administrator" or staff_roles.intersection(frappe.get_roles(user))
		)
		if not self.via_customer_portal and internal_sender:
			if not self.company:
				self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_default("Company")
			return
		return super().set_lead_contact(email_id)
