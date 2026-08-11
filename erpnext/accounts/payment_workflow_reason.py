import frappe

from frappe import _
from frappe.utils import escape_html


PAYMENT_REQUEST_DOCTYPE = "Payment Request"
REASON_FIELD = "custom_workflow_action_reason"
CLIENT_SCRIPT_NAME = "Payments: обов'язкова причина рішення"
RETURN_ACTION = "Повернути на доопрацювання"
REJECT_ACTION = "Відхилити"
REQUIRED_ACTIONS = (RETURN_ACTION, REJECT_ACTION)
REQUIRED_TARGET_STATES = ("Потребує доопрацювання", "Відхилено")
MAX_REASON_LENGTH = 2000

CLIENT_SCRIPT = r'''
frappe.ui.form.on("Payment Request", {
	before_workflow_action(frm) {
		const action = frm.selected_workflow_action;
		const actionsRequiringReason = [
			"Повернути на доопрацювання",
			"Відхилити",
		];

		if (!actionsRequiringReason.includes(action)) {
			return;
		}

		return new Promise((resolve, reject) => {
			let confirmed = false;
			const dialog = new frappe.ui.Dialog({
				title: "Причина",
				fields: [
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: "Причина",
						reqd: 1,
					},
				],
				primary_action_label: "Підтвердити",
				primary_action(values) {
					const reason = (values.reason || "").trim();
					if (!reason) {
						frappe.msgprint("Вкажіть причину рішення.");
						return;
					}

					confirmed = true;
					frm.doc.custom_workflow_action_reason = reason;
					frappe.dom.freeze();
					dialog.hide();
					resolve();
				},
			});

			dialog.$wrapper.on("hidden.bs.modal", () => {
				if (!confirmed) {
					frm.selected_workflow_action = null;
					reject();
				}
			});
			frappe.dom.unfreeze();
			dialog.show();
		});
	},
});
'''.strip()


def sync_workflow_reason_configuration():
	"""Create the standard Client Script used to collect a decision reason."""
	if frappe.db.exists("Client Script", CLIENT_SCRIPT_NAME):
		doc = frappe.get_doc("Client Script", CLIENT_SCRIPT_NAME)
	else:
		doc = frappe.new_doc("Client Script")
		doc.name = CLIENT_SCRIPT_NAME

	doc.dt = PAYMENT_REQUEST_DOCTYPE
	doc.view = "Form"
	doc.enabled = 1
	doc.script = CLIENT_SCRIPT
	_save(doc)
	frappe.clear_cache(doctype=PAYMENT_REQUEST_DOCTYPE)


@frappe.whitelist()
def apply_workflow(doc, action):
	"""Apply the stock workflow while carrying a mandatory decision reason."""
	from frappe.model.workflow import apply_workflow as core_apply_workflow

	payload = frappe.parse_json(doc)
	if payload.get("doctype") != PAYMENT_REQUEST_DOCTYPE:
		return core_apply_workflow(doc, action)

	reason = (payload.get(REASON_FIELD) or "").strip()
	if action in REQUIRED_ACTIONS:
		_validate_reason(reason)

	previous_reason = getattr(frappe.flags, "payments_workflow_reason", None)
	previous_action = getattr(frappe.flags, "payments_workflow_action", None)
	frappe.flags.payments_workflow_reason = reason
	frappe.flags.payments_workflow_action = action

	try:
		result = core_apply_workflow(doc, action)
		if action in REQUIRED_ACTIONS:
			_add_reason_comment(result, action, reason)
		return result
	finally:
		frappe.flags.payments_workflow_reason = previous_reason
		frappe.flags.payments_workflow_action = previous_action


def validate_required_reason(doc, method=None):
	"""Reject direct state changes that bypass the reason-aware workflow call."""
	before = doc.get_doc_before_save()
	if not before:
		return

	previous_state = before.get("workflow_state")
	next_state = doc.get("workflow_state")
	if previous_state == next_state or next_state not in REQUIRED_TARGET_STATES:
		return

	action = getattr(frappe.flags, "payments_workflow_action", None)
	reason = getattr(frappe.flags, "payments_workflow_reason", None)
	if action not in REQUIRED_ACTIONS:
		frappe.throw(
			_("Виконайте перехід через дію робочого процесу та вкажіть причину."),
			title=_("Причина обов'язкова"),
		)
	_validate_reason(reason)


def _validate_reason(reason):
	if not reason:
		frappe.throw(_("Вкажіть причину рішення."), title=_("Причина обов'язкова"))
	if len(reason) > MAX_REASON_LENGTH:
		frappe.throw(
			_("Причина не може містити більше {0} символів.").format(MAX_REASON_LENGTH),
			title=_("Причина занадто довга"),
		)


def _add_reason_comment(doc, action, reason):
	user = frappe.session.user
	actor = frappe.get_cached_value("User", user, "full_name") or user
	verb = "повернув цей запит на доопрацювання" if action == RETURN_ACTION else "відхилив цей запит"
	safe_reason = escape_html(reason).replace("\n", "<br>")
	message = f"<b>{escape_html(actor)}</b> {verb} з причини:<br>{safe_reason}"
	doc.add_comment("Comment", text=message)


def _save(doc):
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
