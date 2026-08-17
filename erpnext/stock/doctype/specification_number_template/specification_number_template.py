import frappe
from frappe.model.document import Document


class SpecificationNumberTemplate(Document):
	def validate(self):
		self.preview = self._build_preview()

	def _build_preview(self):
		parts = []
		for c in self.components or []:
			token = _component_token(c)
			if c.condition_attribute and c.condition_value:
				token = f"[if {c.condition_attribute}={c.condition_value}]{token}"
			parts.append(token)
		# `preview` is a Data field: a template with several attribute tokens overflows it
		return "".join(parts)[:140]


def _component_token(c):
	t = c.component_type
	if t == "Literal":
		return c.value or ""
	if t == "Item Attribute Abbr":
		return "{ATTR:" + (c.attribute_link or "") + ":abbr}"
	if t == "Item Attribute Short Name":
		return "{ATTR:" + (c.attribute_link or "") + ":short_name}"
	if t == "Item Attribute Value":
		return "{ATTR:" + (c.attribute_link or "") + ":value}"
	if t == "Ordinal":
		return "{ORDINAL:" + str(c.ordinal_digits or 2) + "}"
	if t == "Specification Ordinal":
		return "{" + (c.component_role or "?") + ":" + str(c.ordinal_digits or 2) + "}"
	return ""


def _mapped_value(tmpl, attribute, attribute_value):
	for row in tmpl.get("value_map") or []:
		if row.attribute == attribute and row.attribute_value == attribute_value:
			return row.mapped_value
	return None


def _component_in_role(item_doc, role):
	for row in item_doc.get("components") or []:
		if row.get("role") == role:
			return row.get("specification")
	return None


def _condition_matches(component, attr_map):
	if not component.condition_attribute:
		return True
	if not component.condition_value:
		return True
	actual = attr_map.get(component.condition_attribute)
	if actual is None:
		return False
	allowed = {v.strip() for v in component.condition_value.split(",") if v.strip()}
	return str(actual) in allowed


def resolve_specification_template(item_doc):
	"""Resolve Specification Number Template for an Item variant.

	Reads item_doc.specification_number_template + item_doc.attributes; returns the assembled
	specification string, or None if no template / unresolved attributes.
	"""
	tmpl_name = item_doc.get("specification_number_template")
	if not tmpl_name:
		return None
	if not frappe.db.exists("Specification Number Template", tmpl_name):
		return None
	tmpl = frappe.get_cached_doc("Specification Number Template", tmpl_name)
	attr_map = {a.attribute: a.attribute_value for a in (item_doc.get("attributes") or [])}

	parts = []
	for c in tmpl.components or []:
		if not _condition_matches(c, attr_map):
			continue
		t = c.component_type
		if t == "Literal":
			parts.append(c.value or "")
			continue
		if t == "Ordinal":
			ordinal = item_doc.get("ordinal")
			if not ordinal:
				return None
			parts.append(str(int(ordinal)).zfill(int(c.ordinal_digits or 2)))
			continue
		if t == "Specification Ordinal":
			# The board designation carries the catalog position of the coil and the
			# battery it is built from, so this component reads the ordinal off the
			# child specification sitting in that role rather than off this document.
			linked = _component_in_role(item_doc, c.component_role)
			if not linked:
				return None
			ordinal = frappe.db.get_value("Specification", linked, "ordinal")
			if not ordinal:
				return None
			parts.append(str(int(ordinal)).zfill(int(c.ordinal_digits or 2)))
			continue
		attr = c.attribute_link
		if not attr:
			continue
		attr_value = attr_map.get(attr)
		if attr_value is None:
			return None
		# A value can be mapped to its designation text on the template itself, which is
		# how Торгова марка «Укропчик» becomes УКРП without touching the Item attribute.
		mapped = _mapped_value(tmpl, attr, attr_value)
		if mapped:
			parts.append(mapped)
			continue
		if t == "Item Attribute Value":
			parts.append(str(attr_value))
			continue
		field = {"Item Attribute Abbr": "abbr", "Item Attribute Short Name": "short_name"}.get(t)
		if not field:
			continue
		resolved = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr, "attribute_value": attr_value},
			field,
		)
		if not resolved:
			return None
		parts.append(str(resolved))
	result = "".join(parts)
	for ov in tmpl.get("overrides") or []:
		if ov.original_value and ov.original_value == result:
			return ov.override_value or result
	return result
