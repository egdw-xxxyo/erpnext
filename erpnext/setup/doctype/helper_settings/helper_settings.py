import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import NamingSeries

DEFAULT_GUIDE_NAMING_SERIES = "HELP-GUIDE-.YYYY.-.#####"


class HelperSettings(Document):
	def validate(self):
		self.mascot_name = (self.mascot_name or "").strip()
		if not self.mascot_name:
			frappe.throw(_("Enter a mascot name."))
		series = NamingSeries((self.get("guide_naming_series") or "").strip() or DEFAULT_GUIDE_NAMING_SERIES)
		series.validate()
		parts = [part for part in series.series.split(".") if "#" in part]
		if len(parts) != 1 or set(parts[0]) != {"#"}:
			frappe.throw(_("Use one group of # characters after a dot for the guide number."))
		self.guide_naming_series = series.series
