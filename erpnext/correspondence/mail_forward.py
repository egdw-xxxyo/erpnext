import html

import frappe
from frappe import _
from frappe.utils import format_datetime, get_datetime, is_html

from erpnext.correspondence.mail_routing import dedupe_key, parse_patterns, plan_copies, route

FORWARD_JOB = "erpnext.correspondence.mail_forward.forward_communication"
SETTINGS = "Mail Forward Settings"
TEMPLATE = "templates/emails/mail_forward_copy.html"
NOTE_LIMIT = 2000


def watched_mailbox(settings, email_account: str | None):
	return next((row for row in settings.mailboxes if row.email_account == email_account), None)


def is_inbound_email(communication) -> bool:
	return (
		communication.communication_type == "Communication"
		and communication.communication_medium == "Email"
		and communication.sent_or_received == "Received"
		and bool(communication.email_account)
	)


def on_communication_insert(doc, method=None):
	if not is_inbound_email(doc):
		return
	settings = frappe.get_cached_doc(SETTINGS)
	if not settings.enabled or not watched_mailbox(settings, doc.email_account):
		return
	frappe.enqueue(
		FORWARD_JOB,
		queue="default",
		communication=doc.name,
		job_id=f"mail_forward::{doc.name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def own_addresses() -> frozenset[str]:
	accounts = frappe.get_all("Email Account", pluck="email_id")
	recipients = frappe.get_all("Mail Forward Recipient", filters={"email": ["is", "set"]}, pluck="email")
	return frozenset(address.strip().lower() for address in [*accounts, *recipients] if address)


def load_rules() -> list[dict]:
	rules = frappe.get_all(
		"Mail Forward Rule",
		filters={"enabled": 1},
		fields=["name", "email_account", "sender_patterns"],
		order_by="name asc",
	)
	links = frappe.get_all(
		"Mail Forward Rule Recipient",
		filters={"parenttype": "Mail Forward Rule", "parent": ["in", [rule.name for rule in rules] or [""]]},
		fields=["parent", "recipient"],
		order_by="idx asc",
	)
	return [
		{
			"name": rule.name,
			"email_account": rule.email_account,
			"patterns": parse_patterns(rule.sender_patterns),
			"recipients": tuple(link.recipient for link in links if link.parent == rule.name),
		}
		for rule in rules
	]


def load_recipients(codes) -> dict[str, dict]:
	rows = frappe.get_all(
		"Mail Forward Recipient",
		filters={"name": ["in", list(codes) or [""]]},
		fields=["name", "email", "enabled"],
	)
	return {row.name: row for row in rows}


def is_after_cutoff(communication, mailbox) -> bool:
	received = get_datetime(communication.communication_date or communication.creation)
	return not mailbox.forward_since or received >= get_datetime(mailbox.forward_since)


def forward_communication(communication: str):
	comm = frappe.get_doc("Communication", communication)
	settings = frappe.get_single(SETTINGS)
	mailbox = watched_mailbox(settings, comm.email_account)
	sender = (comm.sender or "").strip().lower()
	if not (settings.enabled and is_inbound_email(comm) and mailbox and is_after_cutoff(comm, mailbox)):
		return []
	if not sender or sender in own_addresses():
		return []
	routes = route(load_rules(), sender, comm.email_account)
	copies = plan_copies(routes, load_recipients(routes))
	mailbox_address = frappe.db.get_value("Email Account", comm.email_account, "email_id")
	return [name for name in (send_copy(comm, copy, settings, mailbox_address) for copy in copies) if name]


def send_copy(comm, copy: dict, settings, mailbox_address: str) -> str | None:
	key = dedupe_key(comm.message_id, comm.name, copy["email"] or copy["recipient"])
	if frappe.db.exists("Mail Forward Log", {"dedupe_key": key}):
		return None
	log = frappe.get_doc(
		{
			"doctype": "Mail Forward Log",
			"status": "Skipped" if copy["skip"] else "Queued",
			"note": _(copy["skip"]) if copy["skip"] else None,
			"recipient": copy["recipient"],
			"email": copy["email"],
			"email_account": comm.email_account,
			"communication": comm.name,
			"sender": comm.sender,
			"subject": (comm.subject or "")[:1000],
			"rules": "\n".join(copy["rules"]),
			"message_id": (comm.message_id or "")[:1000],
			"dedupe_key": key,
		}
	)
	try:
		log.insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		return None
	if not copy["skip"]:
		deliver(log, comm, settings, mailbox_address)
	return log.name


def deliver(log, comm, settings, mailbox_address: str):
	try:
		queue = frappe.sendmail(
			recipients=[log.email],
			sender=frappe.db.get_value("Email Account", settings.sender_account, "email_id"),
			subject=f"Fwd: {comm.subject or _('No Subject')}",
			message=render_copy(comm, settings, mailbox_address),
			attachments=[{"fid": name} for name in attached_files(comm.name)],
			reference_doctype="Mail Forward Log",
			reference_name=log.name,
			add_unsubscribe_link=0,
			email_headers={"Auto-Submitted": "auto-generated"},
		)
		log.db_set("email_queue", getattr(queue, "name", None))
	except Exception:
		log.db_set({"status": "Failed", "note": frappe.get_traceback()[-NOTE_LIMIT:]})
		frappe.log_error(
			title=_("Mail forward failed"), reference_doctype="Mail Forward Log", reference_name=log.name
		)


def attached_files(communication: str) -> list[str]:
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Communication", "attached_to_name": communication},
		pluck="name",
		order_by="creation asc",
	)


def body_html(content: str | None) -> str:
	content = content or ""
	return content if is_html(content) else html.escape(content).replace("\n", "<br>")


def render_copy(comm, settings, mailbox_address: str) -> str:
	return frappe.render_template(
		TEMPLATE,
		{
			"sender_name": comm.sender_full_name,
			"sender": comm.sender,
			"date": format_datetime(comm.communication_date) if comm.communication_date else "",
			"to": comm.recipients,
			"cc": comm.cc,
			"subject": comm.subject,
			"mailbox": mailbox_address,
			"body": body_html(comm.content),
			"footer": (settings.footer_note or "").replace("{mailbox}", mailbox_address or ""),
		},
	)
