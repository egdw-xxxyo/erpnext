"""What the customer sees of our side of a WhatsApp chat: read receipts and "typing…".

Both go to Meta as a status update on the customer's newest message. Marking one message
read marks every earlier one read too, and the typing indicator can only ride on a read
receipt — so a manager who starts typing has, from the customer's point of view, read
the chat. Only people who answer the number (Responsible, System Manager) trigger these;
a spectator reading along leaves the customer's messages unread.
"""

import json

import frappe
from frappe.integrations.utils import make_post_request
from frappe_whatsapp.utils import mock

READ = "marked as read"


def _post(account_name, payload):
	account = frappe.get_doc("WhatsApp Account", account_name)
	if mock.is_mock(account):
		return mock.graph_post(account, payload)
	token = account.get_password("token", raise_exception=False)
	if not (token and account.url and account.version and account.phone_id):
		return None
	return make_post_request(
		f"{account.url}/{account.version}/{account.phone_id}/messages",
		headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
		data=json.dumps(payload),
	)


def latest_incoming(chat, upto=None):
	"""The newest customer message of a chat (optionally not newer than `upto`)."""
	filters = {
		"whatsapp_account": chat.whatsapp_account,
		"from": chat.phone,
		"type": "Incoming",
		"content_type": ["!=", "reaction"],
		"message_id": ["is", "set"],
	}
	if upto:
		filters["creation"] = ["<=", upto]
	rows = frappe.get_all(
		"WhatsApp Message",
		filters=filters,
		fields=["name", "status"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def queue_read_receipt(chat, upto=None, typing=False):
	msg = latest_incoming(chat, upto)
	if not msg or (msg.status == READ and not typing):
		return
	frappe.enqueue(
		"erpnext.crm.whatsapp_meta.send_read_receipt",
		queue="short",
		message=msg.name,
		typing=typing,
		enqueue_after_commit=True,
	)


def send_read_receipt(message, typing=False):
	row = frappe.db.get_value(
		"WhatsApp Message", message, ["message_id", "whatsapp_account", "status"], as_dict=True
	)
	if not row or not row.message_id or not row.whatsapp_account:
		return
	payload = {"messaging_product": "whatsapp", "status": "read", "message_id": row.message_id}
	if typing:
		payload["typing_indicator"] = {"type": "text"}
	try:
		response = _post(row.whatsapp_account, payload)
	except Exception:
		frappe.log_error(title="WhatsApp read receipt failed", message=frappe.get_traceback())
		return
	if not (response or {}).get("success"):
		return
	if row.status != READ:
		# set_value skips the doc_events, so no chat refresh fans out for this.
		frappe.db.set_value("WhatsApp Message", message, "status", READ, update_modified=False)
