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


@frappe.whitelist()
def get_item_template_attributes(item_template):
	"""Attributes of the Item template a specification catalog is tied to."""
	if not item_template:
		return []
	return frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_template, "parenttype": "Item"},
		fields=["attribute"],
		order_by="idx",
		pluck="attribute",
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
		self.validate_ordinal()
		self.validate_item_template()
		self.validate_attributes_table()
		self.validate_variant_attributes_on_save()
		self.validate_has_variants()

	def inherit_kind_from_template(self):
		"""A variant belongs to the same ЄСКД catalog as the template it comes from."""
		if not self.variant_of:
			return
		template = frappe.db.get_value(
			"Specification", self.variant_of, ["specification_kind", "item_template"], as_dict=True
		)
		if not template:
			return
		if not self.specification_kind:
			self.specification_kind = template.specification_kind
		self.item_template = template.item_template

	def validate_ordinal(self):
		"""A designation built from a catalog position cannot be issued without one."""
		if self.has_variants or self.ordinal:
			return
		number_template = self.specification_number_template or (
			self.variant_of
			and frappe.db.get_value("Specification", self.variant_of, "specification_number_template")
		)
		if not number_template:
			return
		if frappe.db.exists(
			"Specification Number Template Component",
			{"parent": number_template, "component_type": "Ordinal"},
		):
			frappe.throw(
				_("Ordinal is required — {0} numbers this catalog by its position").format(number_template),
				title=_("Ordinal Missing"),
			)

	def validate_item_template(self):
		"""Tie the catalog to one Item template and keep its attributes the only choice."""
		if not self.item_template:
			self.item_template_attributes = None
			return

		if not frappe.db.get_value("Item", self.item_template, "has_variants"):
			frappe.throw(
				_("{0} is not an Item template — pick an Item that has variants").format(self.item_template)
			)

		allowed = get_item_template_attributes(self.item_template)
		self.item_template_attributes = "\n".join(allowed)

		# Only the axes have to line up with the Item: a variant of this catalog must be
		# describable as a variant of that Item. Attributes pinned on the template are
		# catalog metadata (the ЄСКД organisation) and need no counterpart there.
		if not self.has_variants:
			return

		extra = [
			d.attribute for d in self.attributes or [] if not d.attribute_value and d.attribute not in allowed
		]
		if extra:
			frappe.throw(
				_(
					"Attributes {0} are not on Item template {1}. Give them a fixed value to keep them, or remove them."
				).format(frappe.bold(", ".join(extra)), self.item_template),
				title=_("Attribute Not On Item Template"),
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
		if self.has_variants:
			self.validate_fixed_attribute_values()

	def validate_fixed_attribute_values(self):
		"""A value on a template row fixes that attribute for the whole catalog.

		`УКРП.563562.001-ХХ` covers Li-ion packs only, so the chemistry is pinned on the
		template and every variant of it inherits the value instead of choosing one.
		"""
		for row in self.attributes or []:
			if not row.attribute_value or row.numeric_values:
				continue
			allowed = frappe.get_all(
				"Item Attribute Value",
				filters={"parent": row.attribute, "parenttype": "Item Attribute"},
				pluck="attribute_value",
			)
			if row.attribute_value not in allowed:
				frappe.throw(
					_("{0} is not a value of attribute {1}. Allowed: {2}").format(
						frappe.bold(row.attribute_value), row.attribute, ", ".join(allowed)
					),
					title=_("Invalid Attribute Value"),
				)

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
