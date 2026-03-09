# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Workplace(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed_employees: DF.Table["WorkplaceEmployee"]
		allowed_operations: DF.Table["WorkplaceOperation"]
		company: DF.Link | None
		description: DF.SmallText | None
		is_active: DF.Check
		workplace_name: DF.Data | None
