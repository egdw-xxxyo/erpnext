from frappe.model.document import Document


class CommercialOfferField(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		custom_value: DF.Data | None
		default_value: DF.Data | None
		icon: DF.Data | None
		label: DF.Data
		override: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		preview: DF.Data | None
		section: DF.Literal["Key Capability", "Specification"]
		source_field: DF.Data | None
		source_summary: DF.Data | None
		source_item: DF.Link | None
		source_parameter: DF.Data | None
		unit: DF.Data | None
		value: DF.Data | None
	# end: auto-generated types

	pass
