import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.manufacturing.specification_variant import (
	copy_attributes_to_variant,
	get_variant,
	make_variant_code,
	update_variants,
	validate_variant_attributes,
)


class Specification(Document):
	def autoname(self):
		if self.variant_of and not self.specification_name:
			template = frappe.get_cached_doc("Specification", self.variant_of)
			make_variant_code(template.name, template.specification_name, self)
		if self.specification_name and not self.specification_code:
			self.specification_code = self.specification_name

	def validate(self):
		self.validate_attributes_table()
		self.validate_variant_attributes_on_save()
		self.validate_has_variants()

	def validate_attributes_table(self):
		if self.has_variants or self.variant_of:
			if not self.attributes:
				frappe.throw(_("Attributes table is mandatory for templates and variants"))
			seen = set()
			for row in self.attributes:
				if row.attribute in seen:
					frappe.throw(_("Attribute {0} appears more than once").format(row.attribute))
				seen.add(row.attribute)

	def validate_variant_attributes_on_save(self):
		if not self.variant_of:
			return
		self.attributes = [d for d in self.attributes if d.attribute_value]
		args = {d.attribute: d.attribute_value for d in self.attributes}
		duplicate = get_variant(self.variant_of, args, variant=self.name)
		if duplicate:
			frappe.throw(
				_("A variant with the same attributes already exists: {0}").format(duplicate),
				title=_("Duplicate Variant"),
			)
		validate_variant_attributes(self, args)
		for d in self.attributes:
			d.variant_of = self.variant_of

	def validate_has_variants(self):
		if self.is_new() or self.has_variants:
			return
		if frappe.db.exists("Specification", {"variant_of": self.name}):
			frappe.throw(_("Cannot un-check Has Variants — variants exist for this template"))

	def on_update(self):
		if self.has_variants:
			self.propagate_to_variants()

	def propagate_to_variants(self):
		if frappe.db.get_single_value("Specification Variant Settings", "do_not_update_variants"):
			return
		variants = frappe.get_all("Specification", filters={"variant_of": self.name}, pluck="name")
		if not variants:
			return
		if len(variants) <= 30:
			update_variants(variants, self, publish_progress=False)
		else:
			frappe.enqueue(
				"erpnext.manufacturing.specification_variant.update_variants",
				variants=variants,
				template=self,
				now=frappe.flags.in_test,
				timeout=600,
			)
