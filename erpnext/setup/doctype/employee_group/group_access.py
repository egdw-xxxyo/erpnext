# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Group-based document access.

A DocShare row can point at an Employee Group instead of a single user (see
`frappe/share.py`), so one row grants access to everybody in the group and membership
changes take effect immediately — nothing has to be recalculated per member.

This module supplies the erpnext half:

* `auto_share_on_insert` — when a member of a group creates a document of a doctype the
  group opted into, share that document with the whole group.
* `clear_group_cache` — drop the cached membership when a group changes.
"""

import frappe
import frappe.share

AUTO_SHARE_CACHE_KEY = "auto_share_employee_groups"

#: Ceiling on a single backfill run, matching the cap `frappe.share` puts on inheritance.
SHARE_BACKFILL_LIMIT = 5000


def auto_share_on_insert(doc, method=None):
	"""Share a freshly created document with the author's auto-sharing groups.

	Runs on every insert in the system, so the cheap checks come first: the config is cached
	and is empty on a site that never enabled the feature. `DocShare` itself must be skipped,
	otherwise sharing a document would recurse.
	"""
	if not doc.owner or doc.doctype == "DocShare" or not get_enabled_groups():
		return

	if doc.meta.istable:
		return

	for group in get_auto_share_groups(doc.doctype, doc.owner):
		try:
			frappe.share.add_docshare(
				doc.doctype,
				doc.name,
				share_with_group=group.name,
				read=1,
				write=group.auto_share_write,
				flags={"ignore_share_permission": True},
				notify=0,
			)
		except Exception:
			# a failed share must never block the document being created
			frappe.log_error(
				title="Auto-share to group failed",
				message=f"{doc.doctype} {doc.name} -> {group.name}\n\n{frappe.get_traceback()}",
			)


def get_auto_share_groups(doctype, user):
	"""Groups with auto-sharing enabled for `doctype` that `user` belongs to."""
	enabled = [group for group in get_enabled_groups() if doctype in group.auto_share_doctypes]
	if not enabled:
		return []

	user_groups = set(frappe.share.get_user_groups(user))

	return [group for group in enabled if group.name in user_groups]


def get_enabled_groups():
	"""All Employee Groups with `auto_share_enabled`, with their opted-in doctypes.

	Cached because it is consulted on every document insert.
	"""

	def _fetch():
		if not frappe.db.has_column("Employee Group", "auto_share_enabled"):
			# custom fields not installed yet
			return []

		groups = frappe.get_all(
			"Employee Group",
			filters={"auto_share_enabled": 1},
			fields=["name", "auto_share_write"],
		)

		for group in groups:
			group["auto_share_doctypes"] = frappe.get_all(
				"Access Group Doctype",
				filters={"parent": group.name, "parenttype": "Employee Group"},
				pluck="document_type",
			)

		return groups

	groups = frappe.cache.get_value(AUTO_SHARE_CACHE_KEY, _fetch) or []

	return [frappe._dict(group) for group in groups]


def clear_group_cache(doc=None, method=None):
	"""Invalidate both the membership cache and the auto-share config cache."""
	frappe.cache.delete_key(AUTO_SHARE_CACHE_KEY)
	frappe.share.clear_user_groups_cache()


def on_group_update(doc, method=None):
	"""Refresh caches and reconcile shares for documents that already exist.

	Membership changes need no work at all — a group share is one row and `get_shared`
	resolves the members at read time. Only turning auto-sharing on or off, or changing which
	doctypes it covers, requires touching existing documents.
	"""
	clear_group_cache()

	before = doc.get_doc_before_save()

	was_enabled = bool(before and before.get("auto_share_enabled"))
	is_enabled = bool(doc.get("auto_share_enabled"))

	previous = {row.document_type for row in (before.get("auto_share_doctypes") or [])} if before else set()
	current = {row.document_type for row in (doc.get("auto_share_doctypes") or [])}

	if not is_enabled:
		removed = previous if was_enabled else set()
		added = set()
	else:
		added = current - (previous if was_enabled else set())
		removed = (previous - current) if was_enabled else set()

	for doctype in removed:
		frappe.enqueue(
			"erpnext.setup.doctype.employee_group.group_access.unshare_existing",
			queue="long",
			group=doc.name,
			doctype_to_unshare=doctype,
		)

	for doctype in added:
		frappe.enqueue(
			"erpnext.setup.doctype.employee_group.group_access.backfill_existing",
			queue="long",
			group=doc.name,
			doctype_to_share=doctype,
		)


def backfill_existing(group, doctype_to_share, limit=SHARE_BACKFILL_LIMIT):
	"""Share documents already created by members of `group` with the group."""
	group_doc = frappe.get_cached_doc("Employee Group", group)
	members = [row.user_id for row in group_doc.employee_list if row.user_id]

	if not members:
		return

	already_shared = set(
		frappe.get_all(
			"DocShare",
			filters={"share_doctype": doctype_to_share, "share_with_group": group},
			pluck="share_name",
		)
	)

	names = frappe.get_all(
		doctype_to_share,
		filters={"owner": ("in", members)},
		pluck="name",
		limit_page_length=limit,
	)

	write = 1 if group_doc.get("auto_share_write") else 0

	for name in names:
		if name in already_shared:
			continue

		frappe.share.add_docshare(
			doctype_to_share,
			name,
			share_with_group=group,
			read=1,
			write=write,
			flags={"ignore_share_permission": True},
			notify=0,
		)

	frappe.db.commit()


def unshare_existing(group, doctype_to_unshare):
	"""Drop every share this group holds on a doctype it no longer covers."""
	shares = frappe.get_all(
		"DocShare",
		filters={"share_doctype": doctype_to_unshare, "share_with_group": group},
		pluck="name",
	)

	for share in shares:
		frappe.delete_doc("DocShare", share, ignore_permissions=True, force=True)

	frappe.db.commit()
