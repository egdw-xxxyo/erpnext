import json

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt

from erpnext.buying.procurement_workflow import CONSOLIDATED_FINAL_ASSIGNMENT_RULE_NAME

CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
FINAL_APPROVAL_STATE = "Фінальне погодження"
FINAL_APPROVER_ROLE = "Payments: Фінальний погоджувач"
DEFAULT_APPROVAL_THRESHOLD = 15000
APPROVER_SETTING_FIELDS = ("custom_final_approver_1", "custom_final_approver_2")
APPROVAL_USER_FIELDS = ("final_approved_by_1", "final_approved_by_2")
SNAPSHOT_FIELD = "custom_final_approvers_snapshot"
VOTES_FIELD = "custom_final_approved_users"


def get_approval_threshold():
	return flt(
		frappe.db.get_single_value("Buying Settings", "custom_ceo_approval_threshold")
		or DEFAULT_APPROVAL_THRESHOLD
	)


def is_automatic_final_approval(doc):
	return flt(doc.grand_total) < flt(doc.get("ceo_approval_threshold") or get_approval_threshold())


def _legacy_approvers(settings):
	return list(
		dict.fromkeys(settings.get(field) for field in APPROVER_SETTING_FIELDS if settings.get(field))
	)


def get_configured_final_approvers(throw=True):
	settings = frappe.get_single("Buying Settings")
	if settings.get("custom_final_approvers_initialized") or settings.get("custom_final_approvers"):
		users = [row.approver for row in settings.get("custom_final_approvers") or [] if cint(row.active)]
	else:
		users = _legacy_approvers(settings)
	approvers = list(dict.fromkeys(users))
	valid = [user for user in approvers if _is_valid_approver(user)]
	if throw and (not valid or len(valid) != len(users)):
		frappe.throw(
			_(
				"Configure at least one active, enabled CEO approver with the Final Approver role in Buying Settings. Active approvers must be unique."
			),
			title=_("CEO approvers are not configured"),
		)
	return valid


def _is_valid_approver(user):
	return bool(
		user
		and frappe.db.get_value("User", user, "enabled")
		and frappe.db.exists("Has Role", {"parent": user, "role": FINAL_APPROVER_ROLE})
	)


def validate_final_approver_settings(doc, method=None):
	users = []
	for row in doc.get("custom_final_approvers") or []:
		if not cint(row.active):
			continue
		if row.approver in users or not _is_valid_approver(row.approver):
			frappe.throw(
				_("Active CEO approvers must be unique, enabled users with the Final Approver role.")
			)
		users.append(row.approver)
	doc.custom_final_approvers_initialized = 1


def _read_users(value):
	return list(dict.fromkeys(frappe.parse_json(value) or []))


def get_document_final_approvers(doc):
	if doc.get(SNAPSHOT_FIELD) is not None and doc.get(SNAPSHOT_FIELD) != "":
		return _read_users(doc.get(SNAPSHOT_FIELD))
	return get_configured_final_approvers(throw=False)


def get_document_approved_users(doc):
	users = (
		_read_users(doc.get(VOTES_FIELD))
		if doc.get(VOTES_FIELD)
		else [doc.get(field) for field in APPROVAL_USER_FIELDS if doc.get(field)]
	)
	approvers = get_document_final_approvers(doc)
	return [user for user in dict.fromkeys(users) if user in approvers]


def capture_final_approvers(doc, method=None):
	"""Freeze each approval cycle on entry, preserving server-owned votes on ordinary saves."""
	previous = doc.get_doc_before_save()
	if previous:
		for field in (SNAPSHOT_FIELD, VOTES_FIELD, *APPROVAL_USER_FIELDS, "final_approval_count"):
			doc.set(field, previous.get(field))
	elif doc.is_new():
		for field in (SNAPSHOT_FIELD, VOTES_FIELD, *APPROVAL_USER_FIELDS):
			doc.set(field, None)
		doc.final_approval_count = 0
	entering = doc.workflow_state == FINAL_APPROVAL_STATE and (
		not previous or previous.workflow_state != FINAL_APPROVAL_STATE
	)
	if (
		previous
		and previous.workflow_state == FINAL_APPROVAL_STATE
		and doc.workflow_state == "Погоджено"
		and not is_automatic_final_approval(previous)
	):
		approvers = get_document_final_approvers(previous)
		if (
			not previous.get(SNAPSHOT_FIELD)
			or not approvers
			or set(get_document_approved_users(previous)) != set(approvers)
		):
			frappe.throw(
				_("All CEO approvers recorded for this document must approve before it can advance.")
			)
	if entering:
		approvers = [] if is_automatic_final_approval(doc) else get_configured_final_approvers()
		doc.set(SNAPSHOT_FIELD, json.dumps(approvers))
		doc.set(VOTES_FIELD, "[]")
		for field in APPROVAL_USER_FIELDS:
			doc.set(field, None)
		doc.final_approval_count = 0


def _write_vote(doc, user, update_modified):
	approved = get_document_approved_users(doc)
	approved.append(user)
	values = {VOTES_FIELD: json.dumps(approved), "final_approval_count": len(approved)}
	# Retain the two legacy slots for existing integrations and historical reports.
	values.update(
		{
			field: approved[index] if index < len(approved) else None
			for index, field in enumerate(APPROVAL_USER_FIELDS)
		}
	)
	for field, value in values.items():
		doc.set(field, value)
	frappe.db.set_value(doc.doctype, doc.name, values, update_modified=update_modified)
	_close_user_assignment(doc.name, user)
	return len(approved)


def record_final_approval(doc):
	# Lock the document so concurrent approvals cannot overwrite another user's vote.
	doc = frappe.get_doc(doc.doctype, doc.name, for_update=True)
	doc.check_permission("write")
	if doc.workflow_state != FINAL_APPROVAL_STATE:
		frappe.throw(_("The document is not at the final approval stage."))
	if is_automatic_final_approval(doc):
		frappe.throw(_("This purchase does not require manual CEO approval."))
	approvers = get_document_final_approvers(doc)
	user = frappe.session.user
	if not doc.get(SNAPSHOT_FIELD) or user not in approvers:
		frappe.throw(_("Only a configured CEO approver can approve this purchase."))
	if user in get_document_approved_users(doc):
		if len(get_document_approved_users(doc)) == len(approvers):
			return len(approvers)
		frappe.throw(_("You have already approved this purchase."))
	count = _write_vote(doc, user, update_modified=True)
	actor = frappe.get_cached_value("User", user, "full_name") or user
	doc.add_comment(
		"Comment",
		text=_("{0} recorded CEO approval {1}/{2}.").format(
			f"<b>{escape_html(actor)}</b>", count, len(approvers)
		),
	)
	return count


def record_creator_final_approval(doc, method=None):
	if doc.workflow_state != FINAL_APPROVAL_STATE or is_automatic_final_approval(doc):
		return
	approvers = get_document_final_approvers(doc)
	creator = doc.owner
	if not doc.get(SNAPSHOT_FIELD) or creator not in approvers or creator in get_document_approved_users(doc):
		return
	count = _write_vote(doc, creator, update_modified=False)
	actor = frappe.get_cached_value("User", creator, "full_name") or creator
	doc.add_comment(
		"Comment",
		text=_("{0} recorded CEO approval {1}/{2} as the document creator.").format(
			f"<b>{escape_html(actor)}</b>", count, len(approvers)
		),
		comment_email=creator,
		comment_by=actor,
	)


def reset_final_approvals(docname):
	if not frappe.db.exists(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, docname):
		return
	frappe.db.set_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		docname,
		{
			SNAPSHOT_FIELD: None,
			VOTES_FIELD: None,
			"final_approved_by_1": None,
			"final_approved_by_2": None,
			"final_approval_count": 0,
		},
		update_modified=False,
	)
	close_final_approval_assignments(docname)


def sync_final_approval_assignments(doc, method=None):
	close_final_approval_assignments(doc.name)
	if doc.workflow_state != FINAL_APPROVAL_STATE or is_automatic_final_approval(doc):
		return
	users = [
		user for user in get_document_final_approvers(doc) if user not in get_document_approved_users(doc)
	]
	from erpnext.buying.procurement_automation import notify_procurement_approval

	notify_procurement_approval(
		doc, users, _("Perform final approval of consolidated purchase order {0}.").format(doc.name)
	)


def migrate_final_approver_settings():
	"""Seed the list once; intentionally emptied lists must stay empty on later migrations."""
	settings = frappe.get_single("Buying Settings")
	if settings.get("custom_final_approvers_initialized"):
		return
	if not settings.get("custom_final_approvers"):
		for user in _legacy_approvers(settings):
			settings.append("custom_final_approvers", {"approver": user, "active": 1})
	settings.custom_final_approvers_initialized = 1
	# Schema backfill, not a user edit: avoid validation and operational save hooks.
	settings.update_single(settings.get_valid_dict())
	for row in settings.get("custom_final_approvers") or []:
		if row.is_new():
			row.db_insert()
	frappe.clear_cache(doctype="Buying Settings")


def sync_existing_final_approval_documents():
	"""Freeze legacy reviews once, without transitions, notifications or assignment hooks."""
	settings = frappe.get_single("Buying Settings")
	legacy = _legacy_approvers(settings)
	for name in frappe.get_all(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, pluck="name"):
		doc = frappe.get_doc(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, name)
		if doc.get(SNAPSHOT_FIELD) or (
			doc.workflow_state != FINAL_APPROVAL_STATE and not doc.final_approval_count
		):
			continue
		votes = list(dict.fromkeys(doc.get(field) for field in APPROVAL_USER_FIELDS if doc.get(field)))
		approvers = list(dict.fromkeys([*legacy, *votes])) or get_configured_final_approvers(throw=False)
		frappe.db.set_value(
			doc.doctype,
			doc.name,
			{
				SNAPSHOT_FIELD: json.dumps(approvers),
				VOTES_FIELD: json.dumps(votes),
				"final_approval_count": len(votes),
			},
			update_modified=False,
		)


def sync_existing_approval_thresholds():
	threshold = get_approval_threshold()
	for name in frappe.get_all(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		filters={"workflow_state": ["in", ["Чернетка", "Потребує доопрацювання", "Перевірка підрозділу"]]},
		pluck="name",
	):
		frappe.db.set_value(
			CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			name,
			"ceo_approval_threshold",
			threshold,
			update_modified=False,
		)


def close_final_approval_assignments(docname, method=None):
	if hasattr(docname, "name"):
		docname = docname.name
	_close_assignments(docname, {"assignment_rule": CONSOLIDATED_FINAL_ASSIGNMENT_RULE_NAME})


def _close_user_assignment(docname, user):
	_close_assignments(docname, {"allocated_to": user})


def _close_assignments(docname, extra_filters):
	from erpnext.buying.procurement_automation import _close_assignments_silently

	_close_assignments_silently(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		docname,
		filters={
			"reference_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			"reference_name": docname,
			"status": "Open",
			**extra_filters,
		},
	)
