# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def validate(doc, method=None):
	validate_channel_detail(doc)


def validate_channel_detail(doc):
	if not doc.get("utm_medium"):
		return

	channel = frappe.db.get_value("UTM Medium", doc.utm_medium, "engagement_channel")
	if channel and channel != doc.get("utm_source"):
		frappe.throw(
			_("{0} belongs to the engagement channel {1}").format(
				frappe.bold(doc.utm_medium), frappe.bold(channel)
			),
			title=_("Invalid Engagement Channel Detail"),
		)
