import frappe
from frappe import _
from frappe.desk.form.assign_to import _add as add_assignment
from frappe.utils import escape_html, flt

CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
FINAL_APPROVAL_STATE = "Фінальне погодження"
FINAL_APPROVER_ROLE = "Payments: Фінальний погоджувач"
REQUIRED_FINAL_APPROVALS = 2
DEFAULT_APPROVAL_THRESHOLD = 15000
APPROVER_SETTING_FIELDS = ("custom_final_approver_1", "custom_final_approver_2")
APPROVAL_USER_FIELDS = ("final_approved_by_1", "final_approved_by_2")


def get_approval_threshold():
	return flt(
		frappe.db.get_single_value("Buying Settings", "custom_ceo_approval_threshold")
		or DEFAULT_APPROVAL_THRESHOLD
	)


def is_automatic_final_approval(doc):
	return flt(doc.grand_total) < get_approval_threshold()


def get_configured_final_approvers(throw=True):
	settings = frappe.get_single("Buying Settings")
	approvers = list(
		dict.fromkeys(settings.get(field) for field in APPROVER_SETTING_FIELDS if settings.get(field))
	)
	valid_approvers = [
		user
		for user in approvers
		if frappe.db.get_value("User", user, "enabled")
		and frappe.db.exists("Has Role", {"parent": user, "role": FINAL_APPROVER_ROLE})
	]
	if throw and len(valid_approvers) != REQUIRED_FINAL_APPROVALS:
		frappe.throw(
			_("Configure two enabled CEO approvers with the Final Approver role in Buying Settings."),
			title=_("CEO approvers are not configured"),
		)
	return valid_approvers


def record_final_approval(doc):
	# Serialize the two votes so simultaneous approvals cannot both occupy the
	# first slot and leave the document stuck at 1/2.
	doc = frappe.get_doc(doc.doctype, doc.name, for_update=True)
	doc.check_permission("write")
	if doc.workflow_state != FINAL_APPROVAL_STATE:
		frappe.throw(_("The document is not at the final approval stage."))
	if is_automatic_final_approval(doc):
		frappe.throw(_("This purchase does not require manual CEO approval."))

	approvers = get_configured_final_approvers()
	user = frappe.session.user
	if user not in approvers:
		frappe.throw(_("Only a configured CEO approver can approve this purchase."))

	approved_users = [doc.get(field) for field in APPROVAL_USER_FIELDS if doc.get(field)]
	if user in approved_users:
		frappe.throw(_("You have already approved this purchase."))

	fieldname = APPROVAL_USER_FIELDS[len(approved_users)]
	approved_users.append(user)
	frappe.db.set_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		doc.name,
		{
			fieldname: user,
			"final_approval_count": len(approved_users),
		},
		update_modified=True,
	)
	_close_user_assignment(doc.name, user)

	actor = frappe.get_cached_value("User", user, "full_name") or user
	doc.add_comment(
		"Comment",
		text=_("{0} recorded CEO approval {1}/{2}.").format(
			f"<b>{escape_html(actor)}</b>", len(approved_users), REQUIRED_FINAL_APPROVALS
		),
	)
	return len(approved_users)


def reset_final_approvals(docname):
	if not frappe.db.exists(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, docname):
		return
	frappe.db.set_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		docname,
		{
			"final_approved_by_1": None,
			"final_approved_by_2": None,
			"final_approval_count": 0,
		},
		update_modified=False,
	)
	close_final_approval_assignments(docname)


def sync_final_approval_assignments(doc, method=None):
	if doc.workflow_state != FINAL_APPROVAL_STATE or is_automatic_final_approval(doc):
		close_final_approval_assignments(doc.name)
		return

	approvers = get_configured_final_approvers(throw=False)
	if len(approvers) != REQUIRED_FINAL_APPROVALS:
		return
	approved_users = {doc.get(field) for field in APPROVAL_USER_FIELDS if doc.get(field)}
	users_to_assign = [user for user in approvers if user not in approved_users]
	if not users_to_assign:
		return

	add_assignment(
		{
			"assign_to": users_to_assign,
			"doctype": doc.doctype,
			"name": doc.name,
			"description": _("Review and provide CEO approval for consolidated purchase {0}.").format(
				doc.name
			),
		},
		ignore_permissions=True,
	)


def sync_existing_final_approval_documents():
	"""Migrate open documents to the threshold-based route and assign manual CEO reviews."""
	from frappe.model.workflow import apply_workflow as core_apply_workflow

	for name in frappe.get_all(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		filters={"workflow_state": FINAL_APPROVAL_STATE, "docstatus": 0},
		pluck="name",
	):
		doc = frappe.get_doc(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, name)
		if is_automatic_final_approval(doc):
			result = core_apply_workflow(doc, "Погодити")
			result.add_comment("Comment", text=_("CEO approval was completed automatically by threshold."))
		else:
			sync_final_approval_assignments(doc)


def sync_existing_approval_thresholds():
	threshold = get_approval_threshold()
	for name in frappe.get_all(CONSOLIDATED_PURCHASE_ORDER_DOCTYPE, pluck="name"):
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
	users = set(get_configured_final_approvers(throw=False))
	stored_users = frappe.db.get_value(
		CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
		docname,
		list(APPROVAL_USER_FIELDS),
		as_dict=True,
	) or {}
	users.update(user for user in stored_users.values() if user)
	if not users:
		return

	for todo_name in frappe.get_all(
		"ToDo",
		filters={
			"reference_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			"reference_name": docname,
			"allocated_to": ["in", list(users)],
			"status": "Open",
		},
		pluck="name",
	):
		todo = frappe.get_doc("ToDo", todo_name)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)


def _close_user_assignment(docname, user):
	for todo_name in frappe.get_all(
		"ToDo",
		filters={
			"reference_type": CONSOLIDATED_PURCHASE_ORDER_DOCTYPE,
			"reference_name": docname,
			"allocated_to": user,
			"status": "Open",
		},
		pluck="name",
	):
		todo = frappe.get_doc("ToDo", todo_name)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)
