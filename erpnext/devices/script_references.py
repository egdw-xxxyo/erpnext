"""Named document references for Device and Workplace Scripts.

A script that prints «Упаковка - Крихке» must not carry that name as a string literal:
renaming the Label Template silently breaks the script. Instead the script declares a
reference row (key → DocType + Dynamic Link) and reads `refs.<key>`. `frappe.rename_doc`
rewrites Dynamic Link values, so the row follows the rename and the script keeps working.

References live outside the version snapshot on purpose — a snapshot is a JSON blob that
rename cannot see. They are also separate from Context Fields, so the mobile app never
shows them.

Rows are read straight from the table on every run rather than from the cached parent
document: rename updates child rows with plain SQL, which does not invalidate the cache.
"""

import frappe
from frappe import _


class ScriptRefs(dict):
	"""`refs.<key>` → document name. An undeclared key fails loudly instead of yielding None."""

	def __init__(self, owner, rows=()):
		super().__init__(rows)
		self._owner = owner

	def __getattr__(self, key):
		if key.startswith("_"):
			raise AttributeError(key)
		try:
			return self[key]
		except KeyError:
			raise AttributeError(
				_("{0}: reference «{1}» is not declared in the References table").format(self._owner, key)
			) from None


def load_refs(doctype, name):
	rows = frappe.get_all(
		"Script Reference",
		filters={"parenttype": doctype, "parent": name, "parentfield": "script_references"},
		fields=["key", "ref_name"],
		order_by="idx asc",
	)
	return ScriptRefs(name, ((r.key, r.ref_name) for r in rows))


def validate_refs(doc):
	seen = set()
	for row in doc.get("script_references") or []:
		if not (row.key or "").isidentifier():
			frappe.throw(
				_("Reference key «{0}» must be a Python name: letters, digits, underscores").format(row.key)
			)
		if row.key in seen:
			frappe.throw(_("Reference key «{0}» is declared twice").format(row.key))
		seen.add(row.key)
