import frappe
from frappe import _
from frappe.utils import escape_html

CONSOLIDATED_PURCHASE_ORDER_DOCTYPE = "Consolidated Purchase Order"
REASON_FIELD = "workflow_action_reason"
RETURN_ACTION = "Повернути на доопрацювання"
REJECT_ACTION = "Відхилити"
REQUIRED_ACTIONS = (RETURN_ACTION, REJECT_ACTION)
REQUIRED_TARGET_STATES = ("Потребує доопрацювання", "Відхилено")
MAX_REASON_LENGTH = 2000


def apply_workflow(doc, action):
	from frappe.model.workflow import apply_workflow as core_apply_workflow
	from erpnext.buying.procurement_final_approval import (
		FINAL_APPROVAL_STATE,
		close_final_approval_assignments,
		record_final_approval,
		reset_final_approvals,
	)

	payload = frappe.parse_json(doc)
	current_doc = frappe.get_doc(payload.get("doctype"), payload.get("name"))
	reason = (payload.get(REASON_FIELD) or "").strip()
	if action in REQUIRED_ACTIONS:
		_validate_reason(reason)

	if current_doc.workflow_state == FINAL_APPROVAL_STATE and action == "Погодити":
		approval_count = record_final_approval(current_doc)
		if approval_count < 2:
			frappe.msgprint(
				_("CEO approval {0}/2 recorded. The document is waiting for the second CEO.").format(
					approval_count
				),
				alert=True,
				indicator="orange",
			)
			return frappe.get_doc(current_doc.doctype, current_doc.name)

		result = core_apply_workflow(
			frappe.get_doc(current_doc.doctype, current_doc.name),
			action,
		)
		close_final_approval_assignments(current_doc.name)
		return result

	previous_reason = getattr(frappe.flags, "procurement_workflow_reason", None)
	previous_action = getattr(frappe.flags, "procurement_workflow_action", None)
	frappe.flags.procurement_workflow_reason = reason
	frappe.flags.procurement_workflow_action = action

	try:
		result = core_apply_workflow(doc, action)
		result = _apply_creator_department_approval(result, core_apply_workflow)
		if current_doc.workflow_state == FINAL_APPROVAL_STATE and action in REQUIRED_ACTIONS:
			reset_final_approvals(current_doc.name)
		_add_action_comment(result, action, reason)
		return result
	finally:
		frappe.flags.procurement_workflow_reason = previous_reason
		frappe.flags.procurement_workflow_action = previous_action


def _apply_creator_department_approval(doc, core_apply_workflow):
	"""Advance the department stage when the document creator is a department head."""
	from erpnext.buying.procurement_final_approval import get_configured_final_approvers
	from erpnext.buying.procurement_workflow import DEPARTMENT_HEAD_ROLE

	if doc.workflow_state != "Перевірка підрозділу":
		return doc

	creator = doc.owner
	if not frappe.db.exists("Has Role", {"parent": creator, "role": DEPARTMENT_HEAD_ROLE}):
		return doc
	# A configured CEO must not approve the department stage on their own order.
	# Their creator vote is recorded only after the department head moves the
	# document into the final approval state.
	if creator in get_configured_final_approvers(throw=False):
		return doc

	workflow_action = frappe.db.get_value(
		"Workflow Action",
		{
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"workflow_state": doc.workflow_state,
			"status": "Open",
		},
		"name",
	)
	original_user = frappe.session.user
	try:
		# Administrator performs the technical transition because the workflow keeps
		# self-approval disabled. The Workflow Action and comment are attributed to
		# the actual creator below.
		frappe.set_user("Administrator")
		result = core_apply_workflow(doc, "Погодити")
	finally:
		frappe.set_user(original_user)

	if workflow_action:
		frappe.db.set_value(
			"Workflow Action",
			workflow_action,
			{"completed_by": creator, "completed_by_role": DEPARTMENT_HEAD_ROLE},
			update_modified=False,
		)

	actor = frappe.get_cached_value("User", creator, "full_name") or creator
	result.add_comment(
		"Comment",
		text=_("{0} approved the department review as the document creator.").format(
			f"<b>{escape_html(actor)}</b>"
		),
		comment_email=creator,
		comment_by=actor,
	)
	return result


def validate_required_reason(doc, method=None):
	before = doc.get_doc_before_save()
	if not before:
		return

	previous_state = before.get("workflow_state")
	next_state = doc.get("workflow_state")
	if previous_state == next_state or next_state not in REQUIRED_TARGET_STATES:
		return

	action = getattr(frappe.flags, "procurement_workflow_action", None)
	reason = getattr(frappe.flags, "procurement_workflow_reason", None)
	if action not in REQUIRED_ACTIONS:
		frappe.throw(
			_("Use a workflow action for this transition and provide a reason."),
			title=_("Reason is required"),
		)
	_validate_reason(reason)


def _validate_reason(reason):
	if not reason:
		frappe.throw(_("Enter the reason for the decision."), title=_("Reason is required"))
	if len(reason) > MAX_REASON_LENGTH:
		frappe.throw(
			_("The reason cannot contain more than {0} characters.").format(MAX_REASON_LENGTH),
			title=_("Reason is too long"),
		)


def _add_action_comment(doc, action, reason=None):
	user = frappe.session.user
	actor = frappe.get_cached_value("User", user, "full_name") or user
	action_labels = {
		"Подати на перевірку підрозділу": _("submitted the consolidated order for department review"),
		"Подати повторно": _("resubmitted the consolidated order for department review"),
		"Погодити": _("approved the consolidated order"),
		RETURN_ACTION: _("returned the consolidated order for rework"),
		REJECT_ACTION: _("rejected the consolidated order"),
		"Провести": _("submitted the approved consolidated order"),
	}
	verb = action_labels.get(action, _("performed action “{0}”").format(escape_html(action)))
	message = f"<b>{escape_html(actor)}</b> {verb}."
	if action in REQUIRED_ACTIONS and reason:
		safe_reason = escape_html(reason).replace("\n", "<br>")
		message = _("{0} {1} for the following reason:<br>{2}").format(
			f"<b>{escape_html(actor)}</b>", verb, safe_reason
		)
	doc.add_comment("Comment", text=message)
