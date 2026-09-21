# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""A folder in the register, and the unit permissions are granted on.

A tree rather than a plain field because that is what makes section access free: frappe
expands nested-set descendants when it evaluates a `User Permission`, so a grant on
«Технічні умови» already reaches everything filed below it, and `share_access_inheritance`
carries an explicit share down the same edges.

Names are globally unique, which is the price of `field:section_name`: a `User Permission`
shows the record name, and a hashed name would make granting access unreadable.

Moving a section is safe for permissions in the mechanical sense — the nested set rebuilds
itself and the record name does not change — but the *scope* of every grant on it changes
with the tree. That is a fact for administrators to know, not something code can guard.
"""

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

from erpnext.technical_documentation.constants import DOCUMENT_DOCTYPE


class TechnicalDocumentSection(NestedSet):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link | None
		default_document_type: DF.Link | None
		is_group: DF.Check
		lft: DF.Int
		naming_prefix: DF.Data | None
		old_parent: DF.Link | None
		parent_technical_document_section: DF.Link | None
		rgt: DF.Int
		section_name: DF.Data
	# end: auto-generated types

	nsm_parent_field = "parent_technical_document_section"

	def validate(self):
		self.section_name = (self.section_name or "").strip()

	def on_trash(self):
		self.validate_no_documents()
		super().on_trash()

	def validate_no_documents(self):
		if not frappe.db.table_exists(DOCUMENT_DOCTYPE):
			return

		count = frappe.db.count(DOCUMENT_DOCTYPE, {"section": self.name})
		if count:
			frappe.throw(
				_("Cannot delete section {0}: it holds {1} document(s)").format(frappe.bold(self.name), count)
			)
