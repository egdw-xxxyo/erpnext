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


@frappe.whitelist()
def poll_now():
	"""Run the hourly GitHub poll on demand, from the button on this settings page.

	The scheduler is the normal path; this exists because after changing the token or
	publishing a release nobody wants to wait up to an hour to see whether it worked.
	`poll_github_releases` never raises — it records failures on the Single — so read the
	result back off the document and let the client show it.
	"""
	frappe.only_for("System Manager")

	from erpnext.devices.doctype.mobile_app_release.mobile_app_release import poll_github_releases

	poll_github_releases()
	settings = frappe.get_single("Mobile App Settings")
	return {
		"latest_version": settings.latest_version,
		"last_error": settings.last_error,
		"last_polled_on": str(settings.last_polled_on) if settings.last_polled_on else None,
	}
