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
	"Supplier": lambda row: "{SUPP}",
}

PREVIEW_MAP = {
	"YYYY": lambda: __import__("datetime").datetime.now().strftime("%Y"),
	"YY": lambda: __import__("datetime").datetime.now().strftime("%y"),
	"MM": lambda: __import__("datetime").datetime.now().strftime("%m"),
	"DD": lambda: __import__("datetime").datetime.now().strftime("%d"),
	"ABBR": lambda: frappe.db.get_value("Company", frappe.defaults.get_defaults().get("company"), "abbr")
	or "XX",
	"FY": lambda: __import__("datetime").datetime.now().strftime("%Y"),
	"{SUPP}": lambda: "0",
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

	def on_update(self):
		self._propagate_to_template_items()
		self._apply_start_counting_from()

	def _apply_start_counting_from(self):
		start = cint(self.start_counting_from)
		if start <= 1:
			return

		from frappe.model.naming import NamingSeries

		target = start - 1
		seen_prefixes = set()

		def bump(resolved):
			if not resolved:
				return
			try:
				prefix = NamingSeries(resolved).get_prefix()
			except Exception:
				return
			if prefix in seen_prefixes:
				return
			seen_prefixes.add(prefix)
			frappe.db.sql(
				"""
				INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, %s)
				ON DUPLICATE KEY UPDATE `current` = GREATEST(`current`, VALUES(`current`))
				""",
				(prefix, target),
			)

		items = frappe.get_all(
			"Item",
			filters={"serial_number_template": self.name, "has_variants": 0},
			pluck="name",
		)
		for item_code in items:
			try:
				bump(resolve_series_for_item(self.name, item_code))
			except Exception:
				continue

		bpak_templates = frappe.get_all(
			"BpAK Template",
			filters={"serial_number_template": self.name},
			pluck="name",
		)
		for tmpl_name in bpak_templates:
			try:
				tmpl = frappe.get_doc("BpAK Template", tmpl_name)
				attr_map = {row.attribute: row.attribute_value for row in (tmpl.attributes or [])}
				bump(
					self.resolve_series_from_attributes(
						attr_map, context_label=f"BpAK Template '{tmpl_name}'"
					)
				)
			except Exception:
				continue

	def _propagate_to_template_items(self):
		template_items = frappe.get_all(
			"Item",
			filters={"serial_number_template": self.name, "has_variants": 1},
			pluck="name",
		)
		for item_code in template_items:
			frappe.db.set_value("Item", item_code, "serial_no_series", self.resulting_series)
			item_doc = frappe.get_doc("Item", item_code)
			item_doc.update_variants()

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
	def resolve_series(self, item_code, supplier=None):
		item = frappe.get_doc("Item", item_code)
		attr_map = {d.attribute: d.attribute_value for d in (item.attributes or [])}
		return self.resolve_series_from_attributes(
			attr_map, supplier=supplier, context_label=f"Item '{item_code}'"
		)

	def resolve_series_from_attributes(self, attribute_map, supplier=None, context_label=None):
		"""Resolve {ATTR:Name} and {SUPP} tokens against an explicit attribute name -> value map.

		attribute_map values are looked up in `Item Attribute Value` to find the abbreviation.
		"""
		series = self.resulting_series or ""

		for attr_name, attr_value in (attribute_map or {}).items():
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

		if "{SUPP}" in series:
			supp_abbr = "0"
			if supplier:
				supp_abbr = frappe.db.get_value("Supplier", supplier, "abbr") or "0"
			series = series.replace("{SUPP}", supp_abbr)

		unresolved = re.findall(r"\{ATTR:(.+?)\}", series)
		if unresolved:
			label = context_label or "Document"
			frappe.throw(
				f"{label} is missing attributes: {', '.join(unresolved)}. "
				f"Cannot resolve serial number template."
			)

		return series


@frappe.whitelist()
def resolve_series_for_item(template_name, item_code, supplier=None):
	template = frappe.get_doc("Serial Number Template", template_name)
	return template.resolve_series(item_code, supplier=supplier)


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
