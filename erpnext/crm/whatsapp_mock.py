"""Play the customer side of WhatsApp on dev/test sites.

A WhatsApp Account with `mock_mode` never reaches Meta (see `frappe_whatsapp.utils.mock`).
These endpoints let a manager send messages *as* any phone number to such an account — the
payload goes through the real webhook handler, so it behaves exactly like a message from
Meta. Every endpoint refuses to run on production.
"""

import mimetypes
import time

import frappe
from frappe import _
from frappe_whatsapp.utils import mock

ROLES = ("System Manager", "WhatsApp Manager")
MEDIA_TYPES = ("image", "video", "audio")


def _guard():
	if frappe.conf.get("instance_env") == "prod":
		frappe.throw(_("WhatsApp Mock is not available on production"), frappe.PermissionError)
	frappe.only_for(ROLES)


def _digits(phone):
	return "".join(ch for ch in (phone or "") if ch.isdigit())


def _account(name):
	account = frappe.get_doc("WhatsApp Account", name)
	if not mock.is_mock(account):
		frappe.throw(_("{0} is not in Mock Mode").format(name))
	return account


@frappe.whitelist()
def get_state():
	"""Mock accounts and the numbers that have talked to them."""
	_guard()
	accounts = frappe.get_all(
		"WhatsApp Account",
		filters={"mock_mode": 1},
		fields=["name", "account_name", "display_phone_number", "profile_image"],
	)
	customers = []
	for account in accounts:
		rows = frappe.db.sql(
			"""
			select if(type = 'Incoming', `from`, `to`) as phone,
				max(creation) as last_at,
				max(profile_name) as profile_name
			from `tabWhatsApp Message`
			where whatsapp_account = %s
			group by phone
			order by last_at desc
			""",
			account.name,
			as_dict=True,
		)
		customers += [{**r, "account": account.name} for r in rows if r.phone]
	return {"accounts": accounts, "customers": customers}


@frappe.whitelist()
def get_conversation(account, phone, after=None):
	_guard()
	_account(account)
	phone = _digits(phone)
	filters = {"whatsapp_account": account}
	if after:
		filters["creation"] = [">", after]
	return frappe.get_all(
		"WhatsApp Message",
		filters=filters,
		or_filters={"from": phone, "to": phone},
		fields=[
			"name",
			"type",
			"message",
			"content_type",
			"attach",
			"status",
			"creation",
			"message_id",
			"reply_to_message_id",
			"owner",
		],
		order_by="creation asc",
		limit=500,
	)


@frappe.whitelist()
def send_as_customer(
	account, phone, text=None, file_url=None, profile_name=None, reply_to=None, reaction=None
):
	"""Deliver a customer message to `account` through the webhook handler."""
	_guard()
	account_doc = _account(account)
	phone = _digits(phone)
	if not phone:
		frappe.throw(_("Enter a phone number"))

	message = {
		"from": phone,
		"id": f"wamid.MOCKIN{frappe.generate_hash(length=24)}",
		"timestamp": str(int(time.time())),
	}
	if reply_to and not reaction:
		message["context"] = {"id": reply_to}

	temp_file = None
	if reaction:
		message["type"] = "reaction"
		message["reaction"] = {"message_id": reply_to, "emoji": reaction}
	elif file_url:
		temp_file = frappe.db.get_value("File", {"file_url": file_url}, ["name", "file_name"], as_dict=True)
		if not temp_file:
			frappe.throw(_("File {0} not found").format(file_url))
		mime = mimetypes.guess_type(temp_file.file_name or "")[0] or "application/octet-stream"
		kind = mime.split("/")[0]
		message["type"] = kind if kind in MEDIA_TYPES else "document"
		message[message["type"]] = {"id": f"{mock.MEDIA_PREFIX}{temp_file.name}", "mime_type": mime}
		if text:
			message[message["type"]]["caption"] = text
		if message["type"] == "document":
			message["document"]["filename"] = temp_file.file_name
	else:
		if not (text or "").strip():
			frappe.throw(_("Nothing to send"))
		message["type"] = "text"
		message["text"] = {"body": text}

	mock.post_webhook(
		account_doc,
		{
			"contacts": [{"profile": {"name": profile_name or phone}, "wa_id": phone}],
			"messages": [message],
		},
	)
	if temp_file:
		frappe.delete_doc("File", temp_file.name, ignore_permissions=True)
	return message["id"]
