# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Everything that hangs off a technical document borrows that document's permissions.

Section-level access is two stock mechanisms and no code: a `User Permission` on a
`Technical Document Section` already reaches every section below it, because frappe
expands nested-set descendants, and `share_access_inheritance` carries an explicit share
down the same edges.

Neither of those reaches a revision or a modification, because neither of
them has a `section` field to restrict — they hang off the document through
`technical_document` instead. So the satellites delegate: whoever may read the document
may read what belongs to it, and the list query is filtered by the set of documents the
user may read, as a subquery rather than an expanded list of names.

Files need no rule of their own — `File.has_permission` already defers to whatever they
are attached to.
"""

import frappe

from erpnext.technical_documentation.constants import DOCUMENT_DOCTYPE

PARENT_FIELD = "technical_document"

# A revision is submittable and the document it hangs off is not, so asking the document
# for a `submit` right would always be answered no — there is no such right to grant on a
# doctype that is never submitted. The question the register actually wants answered is
# whether this user may change this document's package, so the submit-side rights are put
# to the parent as `write`, and `amend` as `create`. Refusing a revision's own `cancel`
# stays where it belongs: nobody holds it in the docperms, which are checked first.
PARENT_PTYPES = {"submit": "write", "cancel": "write", "amend": "create"}


def delegate_has_permission(doc, ptype, user, parent_field=PARENT_FIELD):
	parent = doc.get(parent_field)
	if not parent:
		return True

	return frappe.has_permission(DOCUMENT_DOCTYPE, PARENT_PTYPES.get(ptype, ptype), doc=parent, user=user)


def delegate_query_conditions(user=None, doctype=None):
	from frappe.desk.reportview import build_match_conditions

	user = user or frappe.session.user

	if user == "Administrator":
		return ""

	match = build_match_conditions(DOCUMENT_DOCTYPE, user)
	if not match:
		return ""

	return f"""`tab{doctype}`.`{PARENT_FIELD}` in (
		select name from `tab{DOCUMENT_DOCTYPE}` where {match}
	)"""


def revision_has_permission(doc, ptype, user):
	return delegate_has_permission(doc, ptype, user)


def revision_query_conditions(user=None, doctype="Technical Document Revision"):
	return delegate_query_conditions(user, doctype)


def modification_has_permission(doc, ptype, user):
	return delegate_has_permission(doc, ptype, user)


def modification_query_conditions(user=None, doctype="Product Modification"):
	return delegate_query_conditions(user, doctype)


def audit_entry_has_permission(doc, ptype, user):
	return delegate_has_permission(doc, ptype, user, parent_field="document")


def audit_entry_query_conditions(user=None, doctype="Technical Document Audit Entry"):
	from frappe.desk.reportview import build_match_conditions

	user = user or frappe.session.user

	if user == "Administrator":
		return ""

	match = build_match_conditions(DOCUMENT_DOCTYPE, user)
	if not match:
		return ""

	return f"""`tab{doctype}`.`document` in (
		select name from `tab{DOCUMENT_DOCTYPE}` where {match}
	)"""


def relation_has_permission(doc, ptype, user):
	return delegate_has_permission(doc, ptype, user, parent_field="main_document")


def relation_query_conditions(user=None, doctype="Technical Document Relation"):
	from frappe.desk.reportview import build_match_conditions

	user = user or frappe.session.user

	if user == "Administrator":
		return ""

	match = build_match_conditions(DOCUMENT_DOCTYPE, user)
	if not match:
		return ""

	return f"""`tab{doctype}`.`main_document` in (
		select name from `tab{DOCUMENT_DOCTYPE}` where {match}
	)"""
