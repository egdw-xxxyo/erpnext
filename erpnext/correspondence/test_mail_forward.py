from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from erpnext.correspondence.doctype.mail_forward_settings import mail_forward_settings
from erpnext.correspondence.imap_folders import parse_list_response
from erpnext.correspondence.mail_forward import forward_communication

WATCHED = "_Test Watched Mailbox"
SENDER = "_Test Forward Sender"


def make_account(name: str, email: str, **values):
	if frappe.db.exists("Email Account", name):
		frappe.delete_doc("Email Account", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": name,
			"email_id": email,
			"password": "secret",
			"email_server": "imap.example.com",
			"smtp_server": "smtp.example.com",
			**values,
		}
	).insert(ignore_permissions=True)


def make_recipient(code: str, email: str | None, enabled: int = 1):
	frappe.delete_doc("Mail Forward Recipient", code, force=True, ignore_missing=True)
	return frappe.get_doc(
		{"doctype": "Mail Forward Recipient", "code": code, "role": code, "email": email, "enabled": enabled}
	).insert(ignore_permissions=True)


def make_rule(description: str, patterns: str, codes):
	return frappe.get_doc(
		{
			"doctype": "Mail Forward Rule",
			"description": description,
			"sender_patterns": patterns,
			"recipients": [{"recipient": code} for code in codes],
		}
	).insert(ignore_permissions=True)


def receive(sender: str, message_id: str, days_ago: int = 0, email_account: str = WATCHED):
	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"email_account": email_account,
			"sender": sender,
			"sender_full_name": "Bank Manager",
			"recipients": "watched@kalheon.test",
			"subject": "Statement for September",
			"content": "<p>Please find the statement attached.</p>",
			"communication_date": add_days(now_datetime(), -days_ago),
			"message_id": message_id,
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "statement.txt",
			"attached_to_doctype": "Communication",
			"attached_to_name": comm.name,
			"is_private": 1,
			"content": b"balance: 42",
		}
	).insert(ignore_permissions=True)
	return comm


def logs_for(comm):
	return frappe.get_all(
		"Mail Forward Log",
		filters={"communication": comm.name},
		fields=["recipient", "email", "status", "note", "email_queue", "rules"],
		order_by="recipient asc",
	)


class TestMailForward(FrappeTestCase):
	def setUp(self):
		make_account(
			WATCHED,
			"watched@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX"}],
		)
		make_account(SENDER, "robot@kalheon.test", enable_outgoing=1)
		make_recipient("_FIN", "fin@kalheon.test")
		make_recipient("_HR", "hr@kalheon.test")
		make_recipient("_BOSS", "FIN@kalheon.test ")
		make_recipient("_EMPTY", None)
		make_rule("Bank", "@bank.test", ["_FIN", "_BOSS"])
		make_rule("Court", "@court.test", ["_FIN", "_HR", "_EMPTY"])
		settings = frappe.get_single("Mail Forward Settings")
		settings.enabled = 1
		settings.sender_account = SENDER
		settings.set(
			"mailboxes",
			[
				{
					"email_account": WATCHED,
					"folder_mode": "Manual",
					"forward_since": add_days(now_datetime(), -1),
				}
			],
		)
		settings.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_known_sender_gets_one_copy_per_address_with_attachments(self):
		comm = receive("manager@bank.test", "<m1@bank.test>")
		forward_communication(comm.name)
		logs = logs_for(comm)
		self.assertEqual([(log.email, log.status) for log in logs], [("fin@kalheon.test", "Queued")])
		queue = frappe.get_doc("Email Queue", logs[0].email_queue)
		self.assertEqual(queue.sender, "robot@kalheon.test")
		self.assertEqual([row.recipient for row in queue.recipients], ["fin@kalheon.test"])
		self.assertEqual(
			[row["fid"] for row in frappe.parse_json(queue.attachments)],
			frappe.get_all("File", filters={"attached_to_name": comm.name}, pluck="name"),
		)
		self.assertIn("manager@bank.test", queue.message)
		self.assertIn("watched@kalheon.test", queue.message)
		self.assertIn("Auto-Submitted: auto-generated", queue.message)

	def test_unknown_sender_is_ignored(self):
		comm = receive("friend@example.test", "<m2@example.test>")
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])

	def test_recipient_without_email_is_logged_as_skipped(self):
		comm = receive("judge@court.test", "<m3@court.test>")
		forward_communication(comm.name)
		self.assertEqual(
			[(log.recipient, log.status) for log in logs_for(comm)],
			[("_EMPTY", "Skipped"), ("_FIN", "Queued"), ("_HR", "Queued")],
		)

	def test_running_twice_sends_nothing_new(self):
		comm = receive("manager@bank.test", "<m4@bank.test>")
		forward_communication(comm.name)
		forward_communication(comm.name)
		self.assertEqual(len(logs_for(comm)), 1)

	def test_mail_older_than_the_mailbox_is_not_forwarded(self):
		comm = receive("manager@bank.test", "<m5@bank.test>", days_ago=3)
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])

	def test_own_address_as_sender_is_ignored(self):
		comm = receive("robot@kalheon.test", "<m6@kalheon.test>")
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])

	def test_rule_matching_an_own_address_is_refused(self):
		self.assertRaises(frappe.ValidationError, make_rule, "Loop", "@kalheon.test", ["_FIN"])

	def test_mailbox_marking_mail_as_read_is_refused(self):
		frappe.db.set_value("Email Account", WATCHED, "email_sync_option", "UNSEEN")
		settings = frappe.get_single("Mail Forward Settings")
		self.assertRaises(frappe.ValidationError, settings.save)

	def test_sender_sharing_the_watched_address_is_refused(self):
		make_account("_Test Watched SMTP", "Watched@Kalheon.test", enable_outgoing=1)
		settings = frappe.get_single("Mail Forward Settings")
		settings.sender_account = "_Test Watched SMTP"
		self.assertRaises(frappe.ValidationError, settings.save)

	def test_disabled_forwarding_does_nothing(self):
		frappe.db.set_single_value("Mail Forward Settings", "enabled", 0)
		comm = receive("manager@bank.test", "<m7@bank.test>")
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])


SECOND = "_Test Second Mailbox"
SERVER_FOLDERS = parse_list_response(
	[
		b'(\\HasNoChildren \\Inbox) "/" Inbox',
		b'(\\HasNoChildren \\Sent) "/" Sent',
		b'(\\HasNoChildren) "/" Banks',
		b'(\\HasNoChildren) "/" "&BBEEMAQ9BDoEOA-"',
		b'(\\HasNoChildren) "/" Spam',
	]
)


def fake_fetch(account):
	if account.name == SECOND:
		raise ConnectionError("server down")
	return SERVER_FOLDERS


class TestFolderSync(FrappeTestCase):
	def setUp(self):
		make_account(
			WATCHED,
			"watched@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX", "uidvalidity": "77", "uidnext": "1200"}],
		)
		make_account(
			SECOND,
			"second@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX"}],
		)
		settings = frappe.get_single("Mail Forward Settings")
		settings.enabled = 0
		settings.set(
			"mailboxes",
			[
				{"email_account": WATCHED, "folder_mode": "All Folders"},
				{"email_account": SECOND, "folder_mode": "All Folders"},
			],
		)
		settings.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_user_folders_are_added_and_known_ones_keep_their_sync_state(self):
		with patch.object(mail_forward_settings, "fetch_folders", fake_fetch):
			results = mail_forward_settings.sync_all_mailboxes()
		folders = frappe.get_doc("Email Account", WATCHED).imap_folder
		self.assertEqual([row.folder_name for row in folders], ["INBOX", "Banks", "&BBEEMAQ9BDoEOA-"])
		self.assertEqual((folders[0].uidvalidity, folders[0].uidnext), ("77", "1200"))
		self.assertIsNone(results[WATCHED])
		self.assertIn("server down", results[SECOND])

	def test_sync_now_reports_readable_folder_names(self):
		with patch.object(mail_forward_settings, "fetch_folders", fake_fetch):
			results = {row["email_account"]: row for row in mail_forward_settings.sync_folders_now()}
		self.assertEqual(results[WATCHED]["folders"], ["INBOX", "Banks", "Банки"])
		self.assertTrue(results[SECOND]["error"])

	def test_a_failing_mailbox_keeps_its_folders_and_records_the_error(self):
		with patch.object(mail_forward_settings, "fetch_folders", fake_fetch):
			mail_forward_settings.sync_all_mailboxes()
		self.assertEqual(
			[row.folder_name for row in frappe.get_doc("Email Account", SECOND).imap_folder], ["INBOX"]
		)
		row = frappe.get_all(
			"Mail Forward Mailbox",
			filters={"email_account": SECOND},
			fields=["folder_sync_error", "last_folder_sync"],
		)[0]
		self.assertIn("server down", row.folder_sync_error)
		self.assertTrue(row.last_folder_sync)
