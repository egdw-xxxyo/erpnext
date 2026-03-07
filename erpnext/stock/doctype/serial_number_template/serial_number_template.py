# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

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
	"Item Attribute": lambda row: "{ATTR:" + (row.attribute_link or "") + "}",
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


def _get_first_abbr(attribute_name):
	abbr = frappe.db.get_value(
		"Item Attribute Value",
		{"parent": attribute_name},
		"abbr",
		order_by="idx asc",
	)
	return abbr or "???"


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
				attr_match = re.match(r"\{ATTR:(.+)\}", part)
				if attr_match:
					result.append(_get_first_abbr(attr_match.group(1)))
				else:
					result.append(part)
		return "".join(result)

	@frappe.whitelist()
	def resolve_series(self, item_code):
		item = frappe.get_doc("Item", item_code)
		attr_map = {d.attribute: d.attribute_value for d in (item.attributes or [])}

		series = self.resulting_series

		for attr_name, attr_value in attr_map.items():
			token = "{ATTR:" + attr_name + "}"
			if token in series:
				abbr = frappe.db.get_value(
					"Item Attribute Value",
					{"parent": attr_name, "attribute_value": attr_value},
					"abbr",
				)
				if not abbr:
					frappe.throw(
						f"No abbreviation found for attribute '{attr_name}' value '{attr_value}'. "
						f"Please set abbreviations in Item Attribute '{attr_name}'."
					)
				series = series.replace(token, abbr)

		unresolved = re.findall(r"\{ATTR:(.+?)\}", series)
		if unresolved:
			frappe.throw(
				f"Item '{item_code}' is missing attributes: {', '.join(unresolved)}. "
				f"Cannot resolve serial number template."
			)

		return series


@frappe.whitelist()
def resolve_series_for_item(template_name, item_code):
	template = frappe.get_doc("Serial Number Template", template_name)
	return template.resolve_series(item_code)


@frappe.whitelist(allow_guest=True)
def get_qr_svg(value, size=4):
	from io import BytesIO

	from pyqrcode import create as qrcreate

	qr = qrcreate(str(value))
	stream = BytesIO()
	qr.svg(stream, scale=int(size), background="#fff", module_color="#000", xmldecl=False)
	svg = stream.getvalue().decode()
	stream.close()
	return svg
