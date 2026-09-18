# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A link between two documents of the register.

The duplicate rule is forward-only by design: the prototype left one pair recorded twice
and the decision was to keep both rows, so the check runs only when the link itself is
being set or changed. Editing the note on one of those two rows still saves; recreating
the pair does not. A rule applied retroactively would either delete a row nobody asked to
delete, or block every future save of a row that has been fine since 2026.

Removing a relation is a separate, deliberate act, and one of the few the module allows:
the register keeps its documents and their history whatever happens, but a link recorded
by mistake says something untrue about two documents, and taking it back loses nothing.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class TechnicalDocumentRelation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		main_document: DF.Link
		note: DF.SmallText | None
		related_document: DF.Link
		relation_type: DF.Literal[
			"\u0417\u0430\u043c\u0456\u043d\u044e\u0454",
			"\u0417\u0430\u043c\u0456\u043d\u0435\u043d\u0438\u0439 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u043e\u043c",
			"\u041c\u0430\u0454 \u0434\u043e\u0434\u0430\u0442\u043e\u043a",
			"\u0414\u043e\u0434\u0430\u0442\u043e\u043a \u0434\u043e",
			"\u041f\u043e\u0432\u02bc\u044f\u0437\u0430\u043d\u0438\u0439 \u0437",
			"\u0404 \u043f\u0456\u0434\u0441\u0442\u0430\u0432\u043e\u044e \u0434\u043b\u044f",
			"\u0420\u043e\u0437\u0440\u043e\u0431\u043b\u0435\u043d\u0438\u0439 \u043d\u0430 \u043f\u0456\u0434\u0441\u0442\u0430\u0432\u0456",
			"\u0421\u043a\u0430\u0441\u043e\u0432\u0443\u0454",
			"\u041f\u043e\u043f\u0435\u0440\u0435\u0434\u043d\u044f \u0440\u0435\u0434\u0430\u043a\u0446\u0456\u044f",
			"\u041d\u0430\u0441\u0442\u0443\u043f\u043d\u0430 \u0440\u0435\u0434\u0430\u043a\u0446\u0456\u044f",
		]
	# end: auto-generated types

	def validate(self):
		self.validate_not_self_referential()
		self.validate_not_duplicate()

	def link_changed(self):
		before = self.get_doc_before_save()
		if not before:
			return True

		return (before.main_document, before.related_document, before.relation_type) != (
			self.main_document,
			self.related_document,
			self.relation_type,
		)

	def validate_not_self_referential(self):
		if self.main_document == self.related_document:
			frappe.throw(_("A document cannot be related to itself"))

	def validate_not_duplicate(self):
		if not self.link_changed():
			return

		duplicate = frappe.db.get_value(
			self.doctype,
			{
				"main_document": self.main_document,
				"related_document": self.related_document,
				"relation_type": self.relation_type,
				"name": ("!=", self.name),
			},
			"name",
		)
		if duplicate:
			frappe.throw(
				_("Relation {0} already records this link").format(frappe.bold(duplicate)),
				title=_("Duplicate relation"),
			)
