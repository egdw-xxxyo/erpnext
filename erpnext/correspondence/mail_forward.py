import html

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.desk.utils import slug
from frappe.translate import get_user_lang, print_language
from frappe.utils import (
	add_days,
	add_to_date,
	format_datetime,
	get_datetime,
	is_html,
	now_datetime,
)
from frappe.utils.jinja import get_template
from frappe.utils.user import get_users_with_role

from erpnext.correspondence.forwarding_accounts import MANAGER_ROLE
from erpnext.correspondence.mail_routing import dedupe_key, parse_patterns, plan_copies, route

FORWARD_JOB = "erpnext.correspondence.mail_forward.forward_communication"
SETTINGS = "Mail Forward Settings"
TEMPLATE = "templates/emails/mail_forward_copy.html"
NOTE_LIMIT = 2000
QUEUE_OUTCOMES = {"Sent": "Sent", "Error": "Failed"}
PROCESSED_FIELD = "mail_forward_processed"
RECONCILE_WINDOW_DAYS = 3
RECONCILE_DELAY_HOURS = 1
ALERT_ROLES = ("System Manager", MANAGER_ROLE)


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
	if not (settings.enabled and is_inbound_email(comm)):
		return []
	copies = planned_copies(comm, settings)
	mailbox_address = frappe.db.get_value("Email Account", comm.email_account, "email_id")
	sent = [name for name in (send_copy(comm, copy, settings, mailbox_address) for copy in copies) if name]
	frappe.db.set_value("Communication", comm.name, PROCESSED_FIELD, 1, update_modified=False)
	return sent


def planned_copies(comm, settings) -> list[dict]:
	mailbox = watched_mailbox(settings, comm.email_account)
	sender = (comm.sender or "").strip().lower()
	if not (mailbox and is_after_cutoff(comm, mailbox)) or not sender or sender in own_addresses():
		return []
	routes = route(load_rules(), sender, comm.email_account)
	return plan_copies(routes, load_recipients(routes))


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


def sync_delivery_status():
	logs = frappe.get_all(
		"Mail Forward Log",
		filters={"status": "Queued", "email_queue": ["is", "set"]},
		fields=["name", "email_queue"],
	)
	queues = {
		queue.name: queue
		for queue in frappe.get_all(
			"Email Queue",
			filters={
				"name": ["in", [log.email_queue for log in logs] or [""]],
				"status": ["in", list(QUEUE_OUTCOMES)],
			},
			fields=["name", "status", "error"],
		)
	}
	for log in logs:
		if queue := queues.get(log.email_queue):
			frappe.db.set_value(
				"Mail Forward Log",
				log.name,
				{"status": QUEUE_OUTCOMES[queue.status], "note": (queue.error or "")[-NOTE_LIMIT:] or None},
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
	return get_template(TEMPLATE).render(
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


def reconcile_window(settings, now) -> tuple | None:
	if not (settings.enabled and settings.enabled_since):
		return None
	start = max(get_datetime(settings.enabled_since), add_days(now, -RECONCILE_WINDOW_DAYS))
	end = add_to_date(now, hours=-RECONCILE_DELAY_HOURS)
	return (start, end) if start < end else None


def lost_communications(settings, now) -> list[str]:
	window = reconcile_window(settings, now)
	if not window:
		return []
	return frappe.get_all(
		"Communication",
		filters={
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"email_account": ["in", [row.email_account for row in settings.mailboxes] or [""]],
			PROCESSED_FIELD: 0,
			"creation": ["between", window],
		},
		pluck="name",
		order_by="creation asc",
	)


def reconcile_lost_mail(settings, now) -> list[str]:
	lost = lost_communications(settings, now)
	for name in lost:
		forward_communication(name)
	return lost


def account_is_off(name: str | None, *flags: str) -> bool:
	values = frappe.db.get_value("Email Account", name, list(flags), as_dict=True) if name else None
	return not (values and all(values.get(flag) for flag in flags))


def accounts_off(settings) -> int:
	mailboxes = [row.email_account for row in settings.mailboxes]
	sender = [settings.sender_account] if settings.enabled else []
	return sum(account_is_off(name, "enable_incoming", "use_imap") for name in mailboxes) + sum(
		account_is_off(name, "enable_outgoing") for name in sender
	)


def count_problems(settings, since, lost: list[str]) -> dict[str, int]:
	mailboxes = [row.email_account for row in settings.mailboxes]
	accounts = [*mailboxes, settings.sender_account] if settings.sender_account else mailboxes
	return {
		"accounts": accounts_off(settings),
		"lost": len(lost),
		"failed": frappe.db.count("Mail Forward Log", {"status": "Failed", "modified": [">", since]}),
		"unhandled": frappe.db.count(
			"Unhandled Email", {"email_account": ["in", mailboxes or [""]], "creation": [">", since]}
		),
		"errors": frappe.db.count(
			"Error Log",
			{
				"reference_doctype": "Email Account",
				"reference_name": ["in", accounts or [""]],
				"creation": [">", since],
			},
		)
		+ len(
			frappe.get_all(
				"Error Log",
				filters={"creation": [">", since]},
				or_filters={"reference_doctype": "Mail Forward Log", "method": ["like", "%correspondence%"]},
				pluck="name",
			)
		),
		"folders": sum(
			1
			for row in settings.mailboxes
			if row.folder_sync_error and row.last_folder_sync and get_datetime(row.last_folder_sync) > since
		),
	}


def problem_labels() -> dict[str, str]:
	return {
		"accounts": _("Mail accounts that are turned off or missing: {0}"),
		"lost": _("Mail picked up by the hourly check after its forwarding job was lost: {0}"),
		"failed": _("Copies that failed to send: {0}"),
		"unhandled": _("Messages the mailbox could not read: {0}"),
		"errors": _("Errors while reading or forwarding mail: {0}"),
		"folders": _("Mailboxes whose folder sync failed: {0}"),
	}


def alert_subject(counts: dict[str, int]) -> str:
	labels = problem_labels()
	lines = [labels[key].format(count) for key, count in counts.items() if count]
	return "<br>".join([f'<b class="subject-title">{_("Mail forwarding needs attention")}</b>', *lines])


def alert_link(counts: dict[str, int]) -> str:
	doctype = "Mail Forward Log" if counts["lost"] or counts["failed"] else SETTINGS
	return f"/desk/{slug(doctype)}"


def alert_recipients() -> list[str]:
	return sorted({user for role in ALERT_ROLES for user in get_users_with_role(role)})


def notify(counts: dict[str, int]):
	for user in alert_recipients():
		with print_language(get_user_lang(user)):
			make_notification_logs(
				{
					"type": "Alert",
					"subject": alert_subject(counts),
					"link": alert_link(counts),
					"document_type": SETTINGS,
					"document_name": SETTINGS,
				},
				[user],
			)


def check_forwarding_health():
	settings = frappe.get_single(SETTINGS)
	now = now_datetime()
	since = get_datetime(settings.last_health_check or add_to_date(now, hours=-1))
	counts = count_problems(settings, since, reconcile_lost_mail(settings, now))
	frappe.db.set_single_value(SETTINGS, "last_health_check", now, update_modified=False)
	if any(counts.values()):
		notify(counts)
