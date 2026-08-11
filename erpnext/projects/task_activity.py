import frappe

from frappe.utils import escape_html, get_link_to_form


CREATION_LABELS = {
	"Purchase Invoice": "створив рахунок постачальника",
	"Payment Request": "створив запит на оплату",
	"Material Request": "створив замовлення матеріалів",
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
	message = f"<b>{escape_html(actor)}</b> {verb} {document_link} для цього завдання."
	frappe.get_doc("Task", task).add_comment("Info", text=message)
