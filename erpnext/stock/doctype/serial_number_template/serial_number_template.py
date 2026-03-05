# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint


COMPONENT_MAP = {
	"Literal": lambda row: row.value or "",
	"Separator": lambda row: row.value or "-",
	"Year (YYYY)": lambda row: "YYYY",
	"Short Year (YY)": lambda row: "YY",
	"Month (MM)": lambda row: "MM",
	"Day (DD)": lambda row: "DD",
	"Counter": lambda row: "#" * (cint(row.value) or 5),
	"Company Abbreviation": lambda row: "ABBR",
	"Fiscal Year": lambda row: "FY",
}

PREVIEW_MAP = {
	"YYYY": lambda: __import__("datetime").datetime.now().strftime("%Y"),
	"YY": lambda: __import__("datetime").datetime.now().strftime("%y"),
	"MM": lambda: __import__("datetime").datetime.now().strftime("%m"),
	"DD": lambda: __import__("datetime").datetime.now().strftime("%d"),
	"ABBR": lambda: frappe.db.get_value(
		"Company", frappe.defaults.get_defaults().get("company"), "abbr"
	) or "XX",
	"FY": lambda: __import__("datetime").datetime.now().strftime("%Y"),
}


class SerialNumberTemplate(Document):
	def validate(self):
		self.build_series()

	def build_series(self):
		parts = []
		for row in self.components:
			handler = COMPONENT_MAP.get(row.component_type)
			if handler:
				parts.append(handler(row))

		self.resulting_series = ".".join(parts)
		self.preview = self._generate_preview()

	def _generate_preview(self):
		result = []
		for part in self.resulting_series.split("."):
			if part in PREVIEW_MAP:
				result.append(PREVIEW_MAP[part]())
			elif part and all(c == "#" for c in part):
				result.append("0" * (len(part) - 1) + "1")
			else:
				result.append(part)
		return "".join(result)
