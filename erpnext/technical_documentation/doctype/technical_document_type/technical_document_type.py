# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TechnicalDocumentType(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		abbreviation: DF.Data | None
		default_review_months: DF.Int
		default_section: DF.Link | None
		description: DF.SmallText | None
		disabled: DF.Check
		document_type: DF.Data
		has_modifications: DF.Check
		has_product_classification: DF.Check
		requires_approval_by_default: DF.Check
		requires_completeness: DF.Check
		retention_months: DF.Int
	# end: auto-generated types

	pass
