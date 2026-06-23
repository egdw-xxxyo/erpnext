import frappe
from frappe.model.document import Document


class SpecificationNumberTemplate(Document):
	def validate(self):
		self.preview = self._build_preview()

	def _build_preview(self):
		parts = []
		for c in self.components or []:
			t = c.component_type
			if t == "Literal":
				parts.append(c.value or "")
			elif t == "Item Attribute Abbr":
				parts.append("{ATTR:" + (c.attribute_link or "") + ":abbr}")
			elif t == "Item Attribute Short Name":
				parts.append("{ATTR:" + (c.attribute_link or "") + ":short_name}")
			elif t == "Item Attribute Value":
				parts.append("{ATTR:" + (c.attribute_link or "") + ":value}")
		return "".join(parts)


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
		t = c.component_type
		if t == "Literal":
			parts.append(c.value or "")
			continue
		attr = c.attribute_link
		if not attr:
			continue
		attr_value = attr_map.get(attr)
		if attr_value is None:
			return None
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
