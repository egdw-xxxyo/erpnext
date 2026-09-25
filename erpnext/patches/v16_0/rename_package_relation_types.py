# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""The package pair of relation types moves to names that say it is the package.

Completeness is counted off «Має додаток» / «Додаток до» and nothing else, and the names
did not say so: an annex is one kind of package member among several, and a methodology
entered as «Повʼязаний з» looked as good a choice as any. The pair is now «Включає до
комплекту» / «Входить до комплекту». The rows keep their direction — only the words change
— and a second run finds nothing left under the old names.
"""

import frappe

from erpnext.technical_documentation.constants import (
	RELATION_DOCTYPE,
	RELATION_INCLUDED_IN,
	RELATION_INCLUDES,
)

RENAMED = {
	"Має додаток": RELATION_INCLUDES,
	"Додаток до": RELATION_INCLUDED_IN,
}


def execute():
	for old, new in RENAMED.items():
		frappe.db.set_value(
			RELATION_DOCTYPE,
			{"relation_type": old},
			"relation_type",
			new,
			update_modified=False,
		)
