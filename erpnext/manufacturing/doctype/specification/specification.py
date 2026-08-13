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


def _component_map_of(specification):
	rows = frappe.get_all(
		"Specification Component",
		filters={"parent": specification, "parenttype": "Specification"},
		fields=["role", "specification"],
	)
	return {row.role: row.specification for row in rows}


class Specification(Document):
	def autoname(self):
		if self.variant_of and not self.specification_name:
			template = frappe.get_cached_doc("Specification", self.variant_of)
			make_variant_code(template.name, template.specification_name, self)
		if self.variant_of and not self.specification_code:
			# A variant may be given a human name of its own ("Укропчик FO 30 GT") while
			# its designation still has to come from the template's number components.
			self.specification_code = self.resolve_code_from_template()
		if self.specification_name and not self.specification_code:
			self.specification_code = self.specification_name

	def resolve_code_from_template(self):
		from erpnext.stock.doctype.specification_number_template.specification_number_template import (
			resolve_specification_template,
		)

		if not self.specification_number_template and self.variant_of:
			self.specification_number_template = frappe.db.get_value(
				"Specification", self.variant_of, "specification_number_template"
			)
		if not self.specification_number_template:
			return self.specification_name
		return resolve_specification_template(self) or self.specification_name

	def validate(self):
		self.inherit_kind_from_template()
		self.validate_attributes_table()
		self.validate_variant_attributes_on_save()
		self.validate_has_variants()

	def inherit_kind_from_template(self):
		"""A variant belongs to the same ЄСКД catalog as the template it comes from."""
		if self.variant_of and not self.specification_kind:
			self.specification_kind = frappe.db.get_value(
				"Specification", self.variant_of, "specification_kind"
			)

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
		if duplicate and self._same_composition(duplicate):
			frappe.throw(
				_("A variant with the same attributes already exists: {0}").format(duplicate),
				title=_("Duplicate Variant"),
			)
		validate_variant_attributes(self, args)
		for d in self.attributes:
			d.variant_of = self.variant_of

	def _same_composition(self, other):
		"""Two catalog variants can share every attribute and still be different specs.

		A coil differs from its neighbour only by catalog position, and two drones can
		share frame and camera yet be built from a different battery or coil — the
		ordinal and the components are part of the designation, so they are part of the
		identity too.
		"""
		if (self.ordinal or None) != (frappe.db.get_value("Specification", other, "ordinal") or None):
			return False
		return self._component_map() == _component_map_of(other)

	def _component_map(self):
		return {row.role: row.specification for row in self.get("components") or []}

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
