# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OpportunityParticipant(Document):
	pass


def fill_participant_names(doc, method=None):
	"""Populate each participant's display name. Wired on Opportunity `validate`
	because Frappe does not auto-run child-row validate()."""
	for row in doc.get("participants") or []:
		if not row.party:
			continue
		if row.party_type == "Contact":
			row.party_name = frappe.db.get_value("Contact", row.party, "full_name")
		elif row.party_type == "User":
			row.party_name = frappe.db.get_value("User", row.party, "full_name")
