import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from erpnext.setup.doctype.helper_settings.helper_settings import DEFAULT_GUIDE_NAMING_SERIES
from erpnext.setup.helper_guides import validate_guide


class HelperGuide(Document):
	def autoname(self):
		series = frappe.db.get_single_value("Helper Settings", "guide_naming_series")
		self.name = make_autoname(series or DEFAULT_GUIDE_NAMING_SERIES)

	def validate(self):
		validate_guide(self)
