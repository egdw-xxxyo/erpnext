# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MobileAppSettings(Document):
	def validate(self):
		repo = (self.github_repo or "").strip().strip("/")
		if repo and repo.count("/") != 1:
			frappe.throw(_("Repository must be written as owner/name"))
		self.github_repo = repo

	def token(self):
		"""Token for the GitHub API: the one stored here, else site_config's github_token."""
		return self.get_password("github_token", raise_exception=False) or frappe.conf.get("github_token")
