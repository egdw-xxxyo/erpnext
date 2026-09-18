# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""The journal of what happened to a document, which no user may write to.

`Version` already records field diffs, and Track Changes stays on — but a diff cannot say
that a revision was put into force, only that a column changed. This journal records the
business event instead, and it records it in a table where every role has read and
nothing else: entries are written by module code with `ignore_permissions`, so there is no
path through the desk to add or remove one.

The write guards do not stop at permissions, because `Administrator` is checked before
docperms are: an entry refuses to be inserted outside the module and refuses to be changed
at all, whoever is asking. Deleting one is left to `Administrator` alone, which is the
same escape hatch every other record in the register has.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.technical_documentation.audit import AUDIT_FLAG


class TechnicalDocumentAuditEntry(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		comment: DF.SmallText | None
		document: DF.Link
		event: DF.Literal[
			"\u0421\u0442\u0432\u043e\u0440\u0435\u043d\u043e",
			"\u041d\u043e\u0432\u0430 \u0440\u0435\u0434\u0430\u043a\u0446\u0456\u044f",
			"\u0412\u0432\u0435\u0434\u0435\u043d\u043e \u0432 \u0434\u0456\u044e",
			"\u0417\u043c\u0456\u043d\u0430 \u0441\u0442\u0430\u0442\u0443\u0441\u0443",
			"\u0417\u043c\u0456\u043d\u0430 \u0432\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u0430\u043b\u044c\u043d\u043e\u0433\u043e",
			"\u0410\u0440\u0445\u0456\u0432\u043e\u0432\u0430\u043d\u043e",
			"\u0421\u043a\u0430\u0441\u043e\u0432\u0430\u043d\u043e",
			"\u0406\u043d\u0448\u0435",
		]
		event_time: DF.Datetime
		field_changed: DF.Data | None
		revision: DF.Link | None
		user: DF.Link | None
		value_after: DF.SmallText | None
		value_before: DF.SmallText | None
	# end: auto-generated types

	def before_insert(self):
		if not frappe.flags.get(AUDIT_FLAG):
			frappe.throw(_("Audit entries are written by the register itself"))

	def before_save(self):
		if not self.is_new():
			frappe.throw(_("An audit entry cannot be changed once written"))
