import frappe
from frappe import _
from frappe.model.document import Document

IGNORED_FIELDS = {
	"naming_series",
	"specification_code",
	"specification_name",
	"variant_of",
	"has_variants",
	"attributes",
	"variant_name_pattern",
}


class SpecificationVariantSettings(Document):
	def validate(self):
		self.validate_field_names()

	def validate_field_names(self):
		meta = frappe.get_meta("Specification")
		allowed = {f.fieldname for f in meta.fields}
		invalid = []
		for row in self.fields:
			if row.field_name in IGNORED_FIELDS:
				invalid.append(row.field_name)
			elif row.field_name not in allowed:
				invalid.append(row.field_name)
		if invalid:
			frappe.throw(_("Cannot copy fields to variant: {0}").format(", ".join(invalid)))
