# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChatSettings(Document):
	def validate(self):
		# Every value here drives a background job; a zero would mean "immediately" or
		# "never finish", so refuse the whole class of accidents at the form.
		positive = {
			"deep_archive_after_days": _("Deep Archive After (Days)"),
			"deep_archive_batch_size": _("Chats Per Run"),
			"restore_ttl_hours": _("Keep Unpacked Content For (Hours)"),
			"restore_max_messages": _("Maximum Messages To Unpack"),
			"reap_batch_size": _("Cleanup Batch Size"),
			"stale_job_minutes": _("Stuck Job Timeout (Minutes)"),
		}
		for fieldname, label in positive.items():
			value = self.get(fieldname)
			if value is not None and int(value) < 1:
				frappe.throw(_("{0} must be greater than zero").format(label))
