import frappe
from frappe import _
from frappe.utils import escape_html, get_link_to_form

CREATION_LABELS = {
	"Purchase Invoice": "created the Purchase Invoice",
	"Payment Request": "created the Payment Request",
	"Material Request": "created the Material Request",
}


def log_linked_document_creation(doc, method=None):
	"""Write creation of a Task-linked stock/accounting document to the Task timeline."""
	task = doc.get("custom_task")
	verb = CREATION_LABELS.get(doc.doctype)
	if not task or not verb or not frappe.db.exists("Task", task):
		return

	user = frappe.session.user
	actor = frappe.get_cached_value("User", user, "full_name") or user
	document_link = get_link_to_form(doc.doctype, doc.name, escape_html(doc.name))
	message = _("{0} {1} {2} for this task.").format(f"<b>{escape_html(actor)}</b>", _(verb), document_link)
	frappe.get_doc("Task", task).add_comment("Info", text=message)
